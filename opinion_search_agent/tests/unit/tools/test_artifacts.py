import asyncio

import pytest

from opinion_search.tools.artifacts import (
    ArtifactStoreError,
    ArtifactTooLargeError,
    LocalTextArtifactStore,
)


def test_local_artifact_store_is_content_addressed_and_round_trippable(
    tmp_path,
) -> None:
    store = LocalTextArtifactStore(tmp_path / "artifacts", max_bytes=100)

    first = asyncio.run(store.put_text("source body"))
    second = asyncio.run(store.put_text("source body"))

    assert first == second
    assert first.startswith("artifact://sha256/")
    assert asyncio.run(store.get_text(first)) == "source body"
    assert len(tuple((tmp_path / "artifacts").glob("*.txt"))) == 1


def test_local_artifact_store_rejects_oversized_or_invalid_reads(
    tmp_path,
) -> None:
    store = LocalTextArtifactStore(tmp_path / "artifacts", max_bytes=4)

    with pytest.raises(ArtifactTooLargeError):
        asyncio.run(store.put_text("too large"))
    with pytest.raises(ArtifactStoreError, match="reference"):
        asyncio.run(store.get_text("../secret"))
