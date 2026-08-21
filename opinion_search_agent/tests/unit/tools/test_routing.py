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
)
from opinion_search.tools.routing import (
    ProviderBinding,
    RegisteredTool,
    validate_provider_id,
)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class Adapter:
    def __init__(self, marker: str) -> None:
        self.marker = marker

    async def invoke(
        self,
        invocation: ToolInvocation[Arguments],
    ) -> ToolAdapterResponse:
        return ToolAdapterResponse(payload={"marker": self.marker})


def _definition(
    name: str = "search.web",
    capability: str = "search",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Execute search.",
        capability=capability,
        input_model=Arguments,
    )


def _different_definition(name: str = "search.web") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Different description.",
        capability="search",
        input_model=Arguments,
    )


def test_provider_id_validation_accepts_and_rejects() -> None:
    assert validate_provider_id("default") == "default"
    assert validate_provider_id("brave-search") == "brave-search"
    assert validate_provider_id("  a1_b-c  ") == "a1_b-c"

    for bad in ("", "Capital", "1abc", "has space", "x" * 65):
        with pytest.raises(ValueError):
            validate_provider_id(bad)


def test_register_provider_first_provider_creates_default_registered_tool(
) -> None:
    registry = ToolRegistry()
    definition = _definition()
    primary = Adapter("primary")

    registry.register_provider(definition, "primary", primary)
    registered = registry.resolve("search.web")

    assert registered.definition is definition
    assert [binding.provider_id for binding in registered.providers] == ["primary"]
    assert registered.adapter is primary


def test_two_exact_definition_providers_resolve_in_registration_order() -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register_provider(definition, "a", Adapter("a"))
    registry.register_provider(definition, "b", Adapter("b"))

    registered = registry.resolve("search.web")
    assert [binding.provider_id for binding in registered.providers] == ["a", "b"]
    assert [binding.adapter.marker for binding in registered.providers] == ["a", "b"]


def test_duplicate_provider_id_for_one_tool_fails() -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register_provider(definition, "a", Adapter("a"))

    with pytest.raises(DuplicateToolError, match="search.web"):
        registry.register_provider(definition, "a", Adapter("a"))


def test_same_name_different_definition_fails_without_mutating(
) -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register_provider(definition, "a", Adapter("a"))

    with pytest.raises(DuplicateToolError, match="search.web"):
        registry.register_provider(_different_definition(), "b", Adapter("b"))

    registered = registry.resolve("search.web")
    assert [binding.provider_id for binding in registered.providers] == ["a"]


def test_compat_register_maps_to_default_provider() -> None:
    registry = ToolRegistry()
    adapter = Adapter("primary")

    registry.register(_definition(), adapter)
    registered = registry.resolve("search.web")

    assert isinstance(registered, RegisteredTool)
    assert [binding.provider_id for binding in registered.providers] == ["default"]
    assert registered.adapter is adapter


def test_model_specs_are_identical_with_one_or_multiple_providers() -> None:
    single = ToolRegistry()
    single.register_provider(_definition(), "a", Adapter("a"))
    multi = ToolRegistry()
    multi.register_provider(_definition(), "a", Adapter("a"))
    multi.register_provider(_definition(), "b", Adapter("b"))

    assert single.model_specs() == (_definition().model_spec(),)
    assert multi.model_specs() == single.model_specs()
    assert "provider" not in str(single.model_specs()).casefold()


def test_definitions_return_one_per_tool_regardless_of_providers() -> None:
    registry = ToolRegistry()
    registry.register_provider(_definition(), "a", Adapter("a"))
    registry.register_provider(_definition(), "b", Adapter("b"))
    registry.register_provider(_definition("read.web", capability="read"), "a", Adapter("a"))

    assert [item.name for item in registry.definitions()] == [
        "read.web",
        "search.web",
    ]
    assert registry.definitions(capability="search") == (
        registry.resolve("search.web").definition,
    )


def test_provider_binding_round_trip_fields() -> None:
    binding = ProviderBinding(provider_id="brave", adapter=Adapter("x"))

    assert binding.provider_id == "brave"
    assert binding.adapter.marker == "x"
