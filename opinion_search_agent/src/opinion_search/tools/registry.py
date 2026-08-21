from typing import Any

from pydantic import JsonValue

from opinion_search.tools.contracts import ToolAdapter, ToolDefinition
from opinion_search.tools.routing import (
    ProviderBinding,
    RegisteredTool,
    validate_provider_id,
)


class ToolRegistryError(ValueError):
    """Base class for tool registration and resolution failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a stable tool name or provider binding conflicts."""


class UnknownToolError(ToolRegistryError):
    """Raised when a tool name is not present in the registry."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        adapter: ToolAdapter[Any],
    ) -> None:
        """Register a single-provider tool with provider ID ``default``."""
        self.register_provider(definition, "default", adapter)

    def register_provider(
        self,
        definition: ToolDefinition,
        provider_id: str,
        adapter: ToolAdapter[Any],
    ) -> None:
        normalized_provider_id = validate_provider_id(provider_id)
        existing = self._tools.get(definition.name)
        if existing is None:
            self._tools[definition.name] = RegisteredTool(
                definition=definition,
                providers=(
                    ProviderBinding(
                        provider_id=normalized_provider_id,
                        adapter=adapter,
                    ),
                ),
            )
            return

        if existing.definition != definition:
            raise DuplicateToolError(
                "tool is already registered with a different definition: "
                f"{definition.name}"
            )
        if any(
            binding.provider_id == normalized_provider_id
            for binding in existing.providers
        ):
            raise DuplicateToolError(
                f"provider is already bound for tool: {definition.name}"
            )
        self._tools[definition.name] = RegisteredTool(
            definition=existing.definition,
            providers=existing.providers
            + (
                ProviderBinding(
                    provider_id=normalized_provider_id,
                    adapter=adapter,
                ),
            ),
        )

    def resolve(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"unknown tool: {name}") from exc

    def definitions(
        self,
        *,
        capability: str | None = None,
    ) -> tuple[ToolDefinition, ...]:
        definitions = (registered.definition for registered in self._tools.values())
        if capability is not None:
            definitions = (
                definition
                for definition in definitions
                if definition.capability == capability
            )
        return tuple(sorted(definitions, key=lambda item: item.name))

    def model_specs(self) -> tuple[dict[str, JsonValue], ...]:
        return tuple(definition.model_spec() for definition in self.definitions())
