from __future__ import annotations

import asyncio
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol


_ARTIFACT_REF = re.compile(r"^artifact://sha256/([0-9a-f]{64})$")


class ArtifactStoreError(RuntimeError):
    """Base error for local artifact persistence."""


class ArtifactTooLargeError(ArtifactStoreError):
    """Raised before an oversized provider body is persisted."""


class TextArtifactStore(Protocol):
    async def put_text(self, content: str) -> str: ...

    async def get_text(self, artifact_ref: str) -> str: ...


class LocalTextArtifactStore:
    def __init__(self, root: Path, *, max_bytes: int = 2_000_000) -> None:
        if max_bytes < 1:
            raise ValueError("artifact max_bytes must be positive")
        self._root = root
        self._max_bytes = max_bytes

    async def put_text(self, content: str) -> str:
        return await asyncio.to_thread(self._put_text_sync, content)

    async def get_text(self, artifact_ref: str) -> str:
        return await asyncio.to_thread(self._get_text_sync, artifact_ref)

    def _put_text_sync(self, content: str) -> str:
        encoded = content.encode("utf-8")
        if not encoded:
            raise ArtifactStoreError("artifact content must not be empty")
        if len(encoded) > self._max_bytes:
            raise ArtifactTooLargeError(
                f"artifact exceeds the {self._max_bytes}-byte limit"
            )
        digest = sha256(encoded).hexdigest()
        target = self._root / f"{digest}.txt"
        if target.exists():
            return f"artifact://sha256/{digest}"

        temporary_path: Path | None = None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=f".{digest}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, target)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ArtifactStoreError("failed to persist text artifact") from exc
        return f"artifact://sha256/{digest}"

    def _get_text_sync(self, artifact_ref: str) -> str:
        match = _ARTIFACT_REF.fullmatch(artifact_ref)
        if match is None:
            raise ArtifactStoreError("artifact reference is invalid")
        try:
            return (self._root / f"{match.group(1)}.txt").read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactStoreError("failed to read text artifact") from exc
