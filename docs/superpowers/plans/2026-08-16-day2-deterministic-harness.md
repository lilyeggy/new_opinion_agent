# Day 2 Deterministic Harness Implementation Plan

> **For agentic workers:** implement the checklist in order and stop at the review checkpoint before adding fake, checkpoint I/O, or tests.

**Goal:** Turn the Day 1 lifecycle and envelope contracts into a deterministic, resumable single-agent runtime with one authoritative domain-state write path.

**Architecture:** `RunState` owns recoverable runtime facts, `OpinionSearchState` owns domain facts, pure transaction functions advance runtime phases, and a pure reducer applies accepted domain deltas. The async loop only orchestrates injected collaborators and persists recovery boundaries; it does not mutate domain state or contain OpinionSearch completion rules.

**Tech Stack:** Python 3.12, Pydantic 2, async protocols, pytest.

---

## 1. Scope and ownership

### User-owned core semantics

- minimal `OpinionSearchState` and `OpinionSearchDelta`;
- pure domain reducer and its invariants;
- recoverable `RunState`;
- pure step transaction transitions;
- resume classification;
- completion-control contract and terminal-result semantics;
- async loop ordering and checkpoint boundaries.

### Mentor-owned mechanical implementation after review

- model/checkpoint collaborator protocols where mechanical;
- scripted fake model and fake action pipeline;
- versioned atomic JSON checkpoint storage;
- crash-injection fixture;
- reducer, transaction, loop, and resume tests;
- full regression verification.

## 2. File map

### User creates

- `opinion_search_agent/src/opinion_search/domain/opinion/state.py`: minimal authoritative domain state and accepted delta payload.
- `opinion_search_agent/src/opinion_search/domain/opinion/reducer.py`: pure `OpinionSearchState × OpinionSearchDelta -> OpinionSearchState` transition.
- `opinion_search_agent/src/opinion_search/runtime/transaction.py`: recoverable run snapshot, step transaction functions, and resume classification.
- `opinion_search_agent/src/opinion_search/runtime/completion.py`: completion verdict, policy protocol, and terminal run result.
- `opinion_search_agent/src/opinion_search/runtime/loop.py`: explicit async orchestration loop.

### Mentor creates after the core review

- `opinion_search_agent/src/opinion_search/models/contracts.py`
- `opinion_search_agent/src/opinion_search/models/fake.py`
- `opinion_search_agent/src/opinion_search/runtime/checkpoint.py`
- `opinion_search_agent/tests/unit/domain/opinion/test_reducer.py`
- `opinion_search_agent/tests/unit/runtime/test_transaction.py`
- `opinion_search_agent/tests/unit/runtime/test_completion.py`
- `opinion_search_agent/tests/integration/test_offline_loop.py`
- `opinion_search_agent/tests/integration/test_checkpoint_resume.py`

## 3. Required contracts

### 3.1 Minimal domain state

`OpinionSearchState` must be immutable, JSON-round-trippable, and contain only domain facts needed by the Day 2 offline trajectory:

| Field | Required meaning |
|---|---|
| `request` | Original immutable `SearchRequest` |
| `open_gap_ids` | Ordered unique investigation gaps still requiring work |
| `resolved_gap_ids` | Ordered unique gaps already resolved |
| `candidate_source_ids` | Ordered unique candidates discovered by accepted search observations |
| `read_source_ids` | Ordered unique candidates successfully read |
| `reflections` | Ordered accepted internal assessments |
| `revision` | Number of non-duplicate domain deltas that changed the state |

`OpinionSearchDelta` expresses only proposed changes:

| Field | Required meaning |
|---|---|
| `add_candidate_source_ids` | Newly discovered candidate IDs |
| `mark_source_ids_read` | Candidate IDs to mark as read |
| `resolve_gap_ids` | Open gaps to move to resolved |
| `append_reflections` | New reflection text |

The delta must not contain `run_id`, `step_id`, `attempt`, or `action_id`; those already belong to `StateDelta`.

### 3.2 Reducer contract

Expose one public reducer operation with this semantic signature:

```text
reduce_opinion_state(old_state, accepted_delta) -> new_state
```

Required invariants:

- never mutate `old_state`;
- same inputs produce an equal output;
- preserve insertion order while preventing duplicates;
- a read source must already exist in `candidate_source_ids`;
- a resolved gap must currently exist in `open_gap_ids`;
- no ID can be both open and resolved;
- increment `revision` exactly once when the delta has a real effect;
- return the original/equal state without incrementing for a semantic no-op;
- raise a dedicated reducer-invariant exception for illegal deltas;
- perform no I/O and call no model, tool, clock, random generator, or ID generator.

Action-level idempotency does not belong in this domain reducer. It is enforced by the runtime transaction using `StateDelta.action_id` and committed action IDs.

### 3.3 Recoverable run snapshot

`RunState` in `runtime/transaction.py` must contain:

| Field | Required meaning |
|---|---|
| `run_id` | Stable run identity |
| `status` | Day 1 `RunStatus` |
| `domain_state` | Current authoritative domain state |
| `next_step_index` | One-based index for the next logical step |
| `active_step` | Non-committed `StepRecord`, or `None` |
| `committed_steps` | Ordered committed `StepRecord` values |
| `committed_action_ids` | Ordered unique action IDs whose state effects were committed |
| `continuation_pending` | Whether the last committed step still needs a continuation/completion decision |
| `stop_reason` | Terminal human-readable reason, otherwise `None` |
| `failure` | Typed `RuntimeFailure` for failed runs, otherwise `None` |

Local invariants must reject impossible snapshots, including a committed `active_step`, a non-committed record in `committed_steps`, duplicate committed action IDs, and terminal metadata that contradicts `status`.

### 3.4 Pure transaction operations

Provide pure operations for these transitions:

```text
start run
open step
mark deciding
accept decision
start action
record observation
mark reducing
commit accepted delta
terminate run
```

Every operation returns a new `RunState`. It must validate the current lifecycle phase and envelope correlation before advancing.

`commit accepted delta` is the only operation allowed to replace `domain_state`. It must:

1. require an active step in `reducing`;
2. verify the delta correlation and action ID against the active step;
3. return an equal state without reapplying the reducer when the action ID is already committed;
4. otherwise call the injected domain reducer exactly once;
5. atomically append the committed step and action ID, clear `active_step`, replace domain state, increment `next_step_index`, and mark continuation evaluation pending.

Applying the continuation decision is a second pure transaction operation. It clears `continuation_pending` and either keeps the run running or moves it to a terminal status. This makes a crash between state commit and completion evaluation recoverable instead of silently opening an extra step.

### 3.5 Resume classification

Define a small enum or discriminated result representing what the loop must do next. Required mapping:

| Persisted state | Resume action |
|---|---|
| `created` | start run |
| terminal status | return terminal result |
| running with `continuation_pending` | evaluate the last committed step's continuation/completion outcome |
| running, no active step | open next step |
| `opened` or `deciding` | request a decision |
| `decision_accepted` | resolve the accepted decision |
| `action_running` | execute the same stable action ID again |
| `observation_ready` or `reducing` | rebuild/apply the delta without executing the action again |

An active committed step is invalid rather than another resume case.

### 3.6 Completion control

Define four completion dispositions:

- `accept_complete`;
- `reject_and_continue`;
- `accept_partial`;
- `safety_stop`.

A completion verdict contains a disposition and a non-empty reason. A completion policy receives the current domain state and a finish proposal and returns a verdict without mutating state.

`finish` is only a proposal. A rejected finish becomes an internal observation/feedback for a committed step and leaves the run `running`; it must not be represented as search evidence. Accepted completion terminates as `completed`; accepted partial and safety stop terminate as `partial`.

`RunResult` contains the stable run ID, terminal status, final domain state, and stop/failure information. It must reject a non-terminal status.

### 3.7 Explicit async loop

The loop must visibly preserve this order:

```text
initialize or classify resume
-> compile minimal context through a collaborator
-> request structured decision
-> validate against current state
-> resolve accepted decision
-> persist action_running
-> execute action
-> persist observation_ready
-> build accepted StateDelta
-> mark reducing
-> commit through transaction/reducer
-> persist committed snapshot
-> apply completion/continuation outcome
-> persist the cleared/terminal continuation snapshot
```

The loop may call collaborators, but it must not:

- assign to a domain-state field directly;
- construct candidates, evidence, or claims itself;
- inspect provider-specific response objects;
- perform checkpoint file operations directly;
- hide transition order inside LangGraph or another orchestration framework.

The loop must have an explicit hard step limit and cancellation check. Limit exhaustion produces `partial`; cancellation produces `cancelled`, both retaining all committed domain state.

## 4. Crash semantics to preserve

### Before action execution

The checkpoint contains `action_running` and the stable `ActionRequest`. Resume executes that same action ID. The external request may occur more than once if the crash happened after the provider received it but before an observation was saved.

### Observation saved, state not committed

The checkpoint contains `observation_ready` or `reducing`. Resume must not invoke the action again; it rebuilds the deterministic delta and commits it.

### State and step committed, caller did not receive success

The checkpoint contains the committed action ID and new domain state. Resume must not apply the delta again and proceeds from the next step or returns the terminal result.

This is effectively-once state effect, not a claim of exactly-once external search execution.

## 5. User implementation order

- [ ] Create `domain/opinion/state.py` and freeze the minimal state/delta fields.
- [ ] Create `domain/opinion/reducer.py` and implement every reducer invariant.
- [ ] Create `runtime/transaction.py` with `RunState`, transaction transitions, and resume classification.
- [ ] Create `runtime/completion.py` with verdict, policy protocol, run result, and status mapping.
- [ ] Create `runtime/loop.py` with the explicit async orchestration sequence.
- [ ] Run the existing Day 1 suite to ensure no regression.
- [ ] Send the five core files, diff, and design answers for review.

## 6. Review evidence required from the user

- the five user-owned files or their diff;
- output of `pytest -q`;
- reducer invariant table in the user's own words;
- resume result for each persisted phase;
- explanation of why external execution is not exactly-once while state effect can be effectively-once;
- explanation of why finish rejection is feedback rather than evidence.

After this review passes, the mentor adds the fake pipeline, atomic checkpoint I/O, crash injection, and mechanical tests before the Day 2 acceptance gate is declared complete.
