from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from opinion_search.tools.contracts import ToolAdapter, ToolDefinition


ProviderId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    ),
]


def validate_provider_id(provider_id: str) -> str:
    stripped = provider_id.strip()
    if not (1 <= len(stripped) <= 64):
        raise ValueError(
            "provider_id must match ^[a-z][a-z0-9_-]*$ within 1..64 characters"
        )
    first_char, *rest = stripped
    if not first_char.isascii() or not first_char.islower():
        raise ValueError(
            "provider_id must match ^[a-z][a-z0-9_-]*$ within 1..64 characters"
        )
    if not all(_is_provider_id_char(char) for char in rest):
        raise ValueError(
            "provider_id must match ^[a-z][a-z0-9_-]*$ within 1..64 characters"
        )
    return stripped


def _is_provider_id_char(char: str) -> bool:
    return char.isascii() and (
        char.islower() or char.isdigit() or char in {"_", "-"}
    )


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    adapter: ToolAdapter


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    providers: tuple[ProviderBinding, ...]

    @property
    def adapter(self) -> ToolAdapter:
        """The default (first-registered) provider adapter.

        Kept for single-provider compatibility; new consumers should read
        ``providers`` to honor ordered multi-provider bindings.
        """
        return self.providers[0].adapter
