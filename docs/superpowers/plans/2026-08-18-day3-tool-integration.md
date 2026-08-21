# Day 3 Tool Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Day 2 Agent Harness to the Day 3 Tool Runtime so `search` and `read` decisions execute through ToolRegistry/ToolExecutor while `reflect` and `finish` remain typed internal actions.

**Architecture:** Stable Web capability schemas live above provider adapters. The OpinionSearch resolver creates typed planned actions, the app-layer executor reuses `ActionRequest.action_id` when constructing ToolCall, and the domain processor converts normalized outcomes into deltas. The existing AgentLoop, transaction, checkpoint, and Reducer remain unchanged.

**Tech Stack:** Python 3.12, Pydantic 2, asyncio, pytest.

---

## File map

- Create `opinion_search_agent/src/opinion_search/tools/capabilities/__init__.py`.
- Create `opinion_search_agent/src/opinion_search/tools/capabilities/web.py`: provider-neutral Search/Reader schemas.
- Modify `opinion_search_agent/src/opinion_search/tools/adapters/fake.py`: consume stable schemas and record deterministic invocations.
- Create `opinion_search_agent/src/opinion_search/domain/opinion/actions.py`: typed tool and internal actions.
- Create `opinion_search_agent/src/opinion_search/domain/opinion/action_resolver.py`: Decision to planned action mapping.
- Create `opinion_search_agent/src/opinion_search/domain/opinion/processor.py`: typed observations, Tool outcome interpretation, and delta construction.
- Create `opinion_search_agent/src/opinion_search/app/action_executor.py`: ActionRequest to ToolCall bridge plus internal action execution.
- Modify `opinion_search_agent/src/opinion_search/models/fake.py`: surface formal completion/tool feedback in minimal context.
- Create `opinion_search_agent/tests/unit/domain/opinion/test_action_resolver.py`.
- Create `opinion_search_agent/tests/unit/domain/opinion/test_processor.py`.
- Create `opinion_search_agent/tests/integration/test_loop_with_tools.py`.
- Modify `docs/opinion-search-agent-implementation-memory.md`.

## Tasks

- [x] Extract Web capability schemas from the Fake adapter and keep adapter contract tests green.
- [x] Write failing resolver tests for search, read, reflect, finish, and state-aware completion verdicts.
- [x] Implement typed planned actions and OpinionSearchActionResolver.
- [x] Write failing processor tests for search/read success, ToolError no-op, mismatch rejection, reflect, and finish.
- [x] Implement typed observations, app action executor, processor, and completion evaluator.
- [x] Write an end-to-end Tool-backed Loop test proving search/read pass through Registry/Executor and preserve stable action identity.
- [x] Add Tool-backed crash tests for ACTION_RUNNING and OBSERVATION_READY recovery boundaries.
- [x] Run all tests with warnings as errors, compile checks, and whitespace checks.
- [x] Update the implementation memory with the connected execution path and remaining real/MCP adapter work.

## Acceptance criteria

- The formal integration path contains no `FakeActionExecutor`.
- `search/read` invoke ToolExecutor; `reflect/finish` do not invoke ToolExecutor.
- ToolCall action ID equals the enclosing ActionRequest action ID.
- Search results create candidate IDs from normalized URLs; Reader uses that candidate URL in the current minimal state model.
- ToolError produces a committed no-op domain delta and remains available as recent control feedback.
- Crash at ACTION_RUNNING may re-execute the same action ID; crash at OBSERVATION_READY does not re-execute the tool.
- Day 1, Day 2, and standalone Tool Runtime tests remain green.
