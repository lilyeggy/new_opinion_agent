import pytest
from pydantic import BaseModel, ConfigDict

from opinion_search.tools.contracts import (
    ToolAdapterResponse,
    ToolDefinition,
    ToolInvocation,
)
from opinion_search.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class Adapter:
    async def invoke(
        self,
        invocation: ToolInvocation[Arguments],
    ) -> ToolAdapterResponse:
        return ToolAdapterResponse(payload={"value": invocation.arguments.value})


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Execute {name}.",
        capability="test",
        input_model=Arguments,
    )


def test_registry_resolves_definition_and_its_adapter() -> None:
    registry = ToolRegistry()
    definition = _definition("search.web")
    adapter = Adapter()

    registry.register(definition, adapter)
    registered = registry.resolve("search.web")

    assert registered.definition is definition
    assert registered.adapter is adapter


def test_registry_rejects_duplicate_stable_name() -> None:
    registry = ToolRegistry()
    registry.register(_definition("search.web"), Adapter())

    with pytest.raises(DuplicateToolError, match="search.web"):
        registry.register(_definition("search.web"), Adapter())


def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError, match="missing.tool"):
        registry.resolve("missing.tool")


def test_registry_exports_deterministic_model_visible_specs() -> None:
    registry = ToolRegistry()
    registry.register(_definition("read.web"), Adapter())
    registry.register(_definition("search.web"), Adapter())

    assert tuple(item.name for item in registry.definitions()) == (
        "read.web",
        "search.web",
    )
    assert registry.model_specs() == (
        _definition("read.web").model_spec(),
        _definition("search.web").model_spec(),
    )


def test_registry_capability_filter_does_not_expose_adapter() -> None:
    registry = ToolRegistry()
    registry.register(_definition("search.web"), Adapter())

    assert registry.definitions(capability="search") == ()
    assert registry.definitions(capability="test") == (
        registry.resolve("search.web").definition,
    )
