import asyncio
import json
from pathlib import Path

import pytest

from opinion_search.tools.cache import ToolCacheConflictError
from opinion_search.tools.contracts import ToolCall, ToolResult
from opinion_search.tools.persistent_cache import (
    JsonActionResultCache,
    ToolCacheReadError,
)


def _call(*, action_id: str = "action-1", query: str = "topic") -> ToolCall:
    return ToolCall(
        action_id=action_id,
        tool_name="search.web",
        arguments={"query": query},
    )


def _result(*, action_id: str = "action-1") -> ToolResult:
    return ToolResult(
        action_id=action_id,
        tool_name="search.web",
        payload={"items": [{"title": "hit", "url": "https://example.test/hit"}]},
        attempts=3,
    )


def _result_json(cache_dir: Path, action_id: str) -> dict:
    digest_file = _digest_file(cache_dir, action_id)
    return json.loads(digest_file.read_text(encoding="utf-8"))


def _digest_file(cache_dir: Path, action_id: str) -> Path:
    from hashlib import sha256

    digest = sha256(action_id.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def test_persistent_cache_miss_returns_none(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        assert await cache.get(_call()) is None

    asyncio.run(scenario())


def test_persistent_cache_put_get_round_trip(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(), _result())

        assert await cache.get(_call()) == _result()

    asyncio.run(scenario())


def test_persistent_cache_survives_new_process_object(tmp_path) -> None:
    async def scenario() -> None:
        first = JsonActionResultCache(tmp_path)
        await first.put(_call(), _result())

        reconstructed = JsonActionResultCache(tmp_path)
        assert await reconstructed.get(_call()) == _result()

    asyncio.run(scenario())


def test_exact_idempotent_put_is_allowed(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(), _result())
        await cache.put(_call(), _result())

        assert await cache.get(_call()) == _result()

    asyncio.run(scenario())


def test_different_entry_for_same_action_id_raises_conflict(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(query="topic"), _result())

        with pytest.raises(ToolCacheConflictError):
            await cache.put(_call(query="different"), _result())

        # original entry remains readable and unchanged
        assert await cache.get(_call(query="topic")) == _result()

    asyncio.run(scenario())


def test_cached_call_identity_conflict_on_get(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(query="topic"), _result())

        with pytest.raises(ToolCacheConflictError):
            await cache.get(_call(query="different"))

    asyncio.run(scenario())


def test_malformed_json_raises_typed_read_error(tmp_path) -> None:
    digest_file = _digest_file(tmp_path, "action-1")
    digest_file.write_text("{ not valid json ", encoding="utf-8")

    async def scenario() -> None:
        with pytest.raises(ToolCacheReadError):
            await JsonActionResultCache(tmp_path).get(_call())

    asyncio.run(scenario())


def test_unsupported_schema_version_raises_typed_read_error(tmp_path) -> None:
    digest_file = _digest_file(tmp_path, "action-1")
    payload = {
        "schema_version": 999,
        "action_id": "action-1",
        "call": _call().model_dump(mode="json"),
        "result": _result().model_dump(mode="json"),
    }
    digest_file.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    async def scenario() -> None:
        with pytest.raises(ToolCacheReadError):
            await JsonActionResultCache(tmp_path).get(_call())

    asyncio.run(scenario())


def test_truncated_temp_file_is_ignored_on_put(tmp_path) -> None:
    garbage = tmp_path / "deadbeef.json.tmp"
    garbage.write_text("garbage partial write", encoding="utf-8")

    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(), _result())
        assert await cache.get(_call()) == _result()

    asyncio.run(scenario())


def test_get_ignores_leftover_temp_file(tmp_path) -> None:
    garbage = tmp_path / "deadbeef.json.tmp"
    garbage.write_text("garbage partial write", encoding="utf-8")

    async def scenario() -> None:
        assert await JsonActionResultCache(tmp_path).get(_call()) is None

    asyncio.run(scenario())


def test_arbitrary_action_id_is_path_safe(tmp_path) -> None:
    nasty_action_id = "../../escape/../etc/action"

    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(action_id=nasty_action_id), _result(action_id=nasty_action_id))

        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".json"
        assert files[0].parent == tmp_path
        assert await cache.get(_call(action_id=nasty_action_id)) == _result(
            action_id=nasty_action_id
        )

    asyncio.run(scenario())


def test_cache_payload_contains_exactly_schema_fields(tmp_path) -> None:
    async def scenario() -> None:
        cache = JsonActionResultCache(tmp_path)
        await cache.put(_call(), _result())

        payload = _result_json(tmp_path, "action-1")
        assert set(payload) == {"schema_version", "action_id", "call", "result"}
        assert payload["schema_version"] == 1
        assert payload["action_id"] == "action-1"
        call_fields = set(payload["call"])
        result_fields = set(payload["result"])
        assert call_fields <= {"action_id", "tool_name", "arguments"}
        assert result_fields <= {"action_id", "tool_name", "payload", "artifact_refs", "attempts"}

    asyncio.run(scenario())


def test_no_temporary_file_remains_after_success(tmp_path) -> None:
    async def scenario() -> None:
        await JsonActionResultCache(tmp_path).put(_call(), _result())

    asyncio.run(scenario())

    assert not list(tmp_path.glob("*.tmp"))
