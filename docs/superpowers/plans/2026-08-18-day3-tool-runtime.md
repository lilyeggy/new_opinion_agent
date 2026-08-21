# Day 3 Tool Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-independent Tool Runtime that validates calls, resolves registered capabilities, applies deterministic timeout/retry/cancellation rules, and normalizes adapter responses and failures.

**Architecture:** The Agent Harness continues to own run/step transactions. `ToolRegistry` owns capability discovery, `ToolExecutor` owns execution policy, and thin adapters own provider translation. Tool output remains JSON-safe untrusted data and cannot update OpinionSearch state without the existing Observation processor and Reducer path.

**Tech Stack:** Python 3.12, Pydantic 2, asyncio, pytest.

---

## Scope

This increment implements the core Tool Runtime and deterministic Fake Search/Reader adapters. It does not add HTTP provider code or MCP transport, and it does not change the Day 2 AgentLoop.

## File map

- Create `opinion_search_agent/src/opinion_search/tools/__init__.py`: package boundary.
- Create `opinion_search_agent/src/opinion_search/tools/contracts.py`: stable tool models, adapter invocation contract, typed errors, and retry policy.
- Create `opinion_search_agent/src/opinion_search/tools/registry.py`: registration, duplicate rejection, resolution, and model-visible schema export.
- Create `opinion_search_agent/src/opinion_search/tools/executor.py`: argument validation, timeout, retries, cancellation propagation, and result normalization.
- Create `opinion_search_agent/src/opinion_search/tools/adapters/__init__.py`: adapter package boundary.
- Create `opinion_search_agent/src/opinion_search/tools/adapters/fake.py`: deterministic Fake Search and Reader definitions/adapters.
- Create `opinion_search_agent/tests/unit/tools/test_contracts.py`: contract invariants.
- Create `opinion_search_agent/tests/unit/tools/test_registry.py`: registry behavior.
- Create `opinion_search_agent/tests/unit/tools/test_executor.py`: execution and recovery policy.
- Create `opinion_search_agent/tests/contract/test_fake_tool_adapters.py`: same public contract for fake search/read.
- Modify `docs/opinion-search-agent-implementation-memory.md`: append verified Day 3 Tool Runtime facts.

## Task 1: Freeze contracts with tests

- [x] Write tests proving tool names/descriptions are non-empty, JSON payloads are serializable, attempt numbers start at one, error retryability is derived from stable error kinds, and retry policy validates positive limits.
- [x] Run the focused tests and confirm failure because the package does not exist.
- [x] Implement `ToolDefinition`, `ToolCall`, `ToolInvocation`, `ToolAdapterResponse`, `ToolResult`, `ToolErrorKind`, `ToolError`, `ToolAdapterError`, `RetryPolicy`, and `ToolAdapter`.
- [x] Re-run the focused tests.

## Task 2: Implement ToolRegistry test-first

- [x] Write tests for registration, duplicate rejection, unknown resolution, deterministic definition ordering, adapter association, and model-visible schema export.
- [x] Run the focused tests and confirm failure.
- [x] Implement the registry without provider-specific branches.
- [x] Re-run the focused tests.

## Task 3: Implement ToolExecutor test-first

- [x] Write tests for validation before adapter invocation, success normalization, timeout retry, rate-limit/server retry, non-retryable failures, stable action identity across attempts, cancellation propagation, and exhausted retry metadata.
- [x] Run the focused tests and confirm failure.
- [x] Implement the executor with injected sleep and `asyncio.timeout`.
- [x] Re-run the focused tests.

## Task 4: Implement deterministic Fake Search and Reader

- [x] Write contract tests for successful search/read and normalized not-found/unreadable failures.
- [x] Run the focused tests and confirm failure.
- [x] Implement typed input/result models and thin fake adapters.
- [x] Re-run the focused tests.

## Task 5: Integration and documentation

- [x] Run the complete suite with warnings treated as errors.
- [x] Run compile and whitespace checks.
- [x] Review the implementation against the canonical Day 3 contracts and scope.
- [x] Append the implemented contracts, retry table, trust boundary, test evidence, and next integration point to the implementation memory.
- [x] Re-run documentation and full regression checks.

## Acceptance criteria

- Replacing an adapter does not change ToolRegistry or ToolExecutor.
- Invalid arguments never reach an adapter.
- Retryable failures retain the same action ID and increment only the tool attempt.
- Authentication, permission, invalid arguments, not-found, unreadable content, and unknown provider failures do not retry.
- Async task cancellation is propagated immediately and stops retry/backoff.
- Tool payloads are JSON-safe untrusted data, not provider objects and not State mutations.
- Existing Day 1 and Day 2 tests remain green.
