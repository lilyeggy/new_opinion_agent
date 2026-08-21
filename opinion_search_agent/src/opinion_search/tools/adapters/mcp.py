from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import re
from hashlib import sha256
from typing import ClassVar, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    model_validator,
)
from typing import Annotated, Self

from opinion_search.tools.contracts import (
    ToolAdapterError,
    ToolAdapterResponse,
    ToolDefinition,
    ToolErrorKind,
    ToolInvocation,
)
from opinion_search.tools.registry import ToolRegistry
from opinion_search.tools.registry import UnknownToolError


_SERVER_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class McpToolDiscoveryError(ValueError):
    """Raised when an MCP server exposes an unsafe or invalid tool contract."""


class McpToolBinding(BaseModel):
    """App-owned allowlist binding reviewed against the remote descriptor.

    The local description and capability come from the app config, never from
    the remote descriptor. Canonical JSON schema hashes pin the reviewed
    remote input/output contract before any local registration.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    remote_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    local_description: Annotated[str, Field(min_length=1)]
    capability: Annotated[str, Field(min_length=1)]
    expected_input_schema_sha256: Annotated[str, Field(min_length=64, max_length=64)]
    expected_output_schema_sha256: Annotated[
        str,
        Field(min_length=64, max_length=64),
    ] | None = None

    @model_validator(mode="after")
    def validate_hash_formats(self) -> Self:
        if not _SHA256_PATTERN.fullmatch(self.expected_input_schema_sha256):
            raise ValueError("expected_input_schema_sha256 must be a lowercase hex digest")
        if (
            self.expected_output_schema_sha256 is not None
            and not _SHA256_PATTERN.fullmatch(self.expected_output_schema_sha256)
        ):
            raise ValueError(
                "expected_output_schema_sha256 must be a lowercase hex digest"
            )
        return self


def canonical_schema_hash(schema: dict[str, JsonValue]) -> str:
    """Lowercase SHA-256 of the canonical JSON serialization of a schema."""
    serialized = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class McpToolDescriptor(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    description: str = Field(min_length=1)
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue] | None = None
    annotations: dict[str, JsonValue] | None = Field(
        default=None,
        exclude=True,
    )


class McpListToolsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tools: tuple[McpToolDescriptor, ...]
    next_cursor: str | None = None


class McpCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: tuple[JsonValue, ...] = ()
    structured_content: dict[str, JsonValue] | None = None
    is_error: bool = False


class McpTransport(Protocol):
    async def list_tools(
        self,
        *,
        cursor: str | None = None,
    ) -> McpListToolsResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpCallResult: ...


class FakeMcpTransport:
    """Deterministic transport for discovery and invocation contract tests."""

    def __init__(
        self,
        *,
        tools: tuple[McpToolDescriptor, ...] = (),
        pages: Mapping[str | None, McpListToolsResult] | None = None,
        results: Mapping[str, McpCallResult] | None = None,
    ) -> None:
        self._pages = (
            dict(pages)
            if pages is not None
            else {None: McpListToolsResult(tools=tools)}
        )
        self._results = dict(results or {})
        self.list_cursors: list[str | None] = []
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
    ) -> McpListToolsResult:
        self.list_cursors.append(cursor)
        try:
            return self._pages[cursor]
        except KeyError as exc:
            raise McpToolDiscoveryError(
                f"MCP discovery returned an unknown cursor: {cursor!r}"
            ) from exc

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpCallResult:
        self.calls.append((name, dict(arguments)))
        try:
            return self._results[name]
        except KeyError as exc:
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "The MCP server did not return a tool result.",
            ) from exc


class _McpArguments(RootModel[dict[str, JsonValue]]):
    model_config = ConfigDict(frozen=True)

    _json_schema: ClassVar[dict[str, JsonValue]]
    _validator: ClassVar[Draft202012Validator]

    @model_validator(mode="after")
    def validate_json_schema(self) -> _McpArguments:
        try:
            self._validator.validate(self.root)
        except JsonSchemaError as exc:
            raise ValueError("arguments do not match MCP input schema") from exc
        return self

    @classmethod
    def model_json_schema(cls, *args: object, **kwargs: object) -> dict:
        del args, kwargs
        return deepcopy(cls._json_schema)


def _arguments_model(
    qualified_name: str,
    schema: dict[str, JsonValue],
) -> type[_McpArguments]:
    class_name = "McpArguments_" + re.sub(r"[^A-Za-z0-9_]", "_", qualified_name)
    return type(
        class_name,
        (_McpArguments,),
        {
            "_json_schema": deepcopy(schema),
            "_validator": Draft202012Validator(schema),
        },
    )


class McpToolAdapter:
    def __init__(
        self,
        transport: McpTransport,
        descriptor: McpToolDescriptor,
    ) -> None:
        self._transport = transport
        self._descriptor = descriptor
        self._output_validator = (
            Draft202012Validator(descriptor.output_schema)
            if descriptor.output_schema is not None
            else None
        )

    async def invoke(
        self,
        invocation: ToolInvocation[_McpArguments],
    ) -> ToolAdapterResponse:
        result = await self._transport.call_tool(
            self._descriptor.name,
            invocation.arguments.root,
        )
        if result.is_error:
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "The MCP tool reported an execution error.",
            )

        if self._output_validator is not None and result.structured_content is None:
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "The MCP tool did not return structured content for its "
                "declared output schema.",
            )

        if result.structured_content is not None:
            payload: JsonValue = result.structured_content
            if self._output_validator is not None:
                try:
                    self._output_validator.validate(payload)
                except JsonSchemaError as exc:
                    raise ToolAdapterError(
                        ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                        "The MCP tool returned invalid structured content.",
                    ) from exc
        else:
            payload = {"content": list(result.content)}

        return ToolAdapterResponse(payload=payload)


async def register_mcp_tools(
    registry: ToolRegistry,
    transport: McpTransport,
    *,
    server_id: str,
    bindings: tuple[McpToolBinding, ...],
) -> tuple[str, ...]:
    """Allowlist and schema-pin MCP tools before atomic local registration.

    Every discovered remote tool is untrusted. The app-owned ``bindings``
    decide which remote tools may be registered, what local description and
    capability they get, and what reviewed schema hashes must match. Only after
    every allowlisted remote name is found exactly once, all schemas validate,
    all hashes match, and every Registry conflict is checked does this function
    register all pending tools. Any failure leaves the Registry byte-for-byte
    unchanged and reports only remote name plus expected/actual hashes — never
    the mismatched schema body.
    """
    if not _SERVER_ID_PATTERN.fullmatch(server_id):
        raise McpToolDiscoveryError(
            "server_id must be a stable alphanumeric namespace"
        )
    if not bindings:
        raise McpToolDiscoveryError(
            "at least one allowlisted MCP binding is required"
        )

    descriptors: list[McpToolDescriptor] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    while True:
        page = await transport.list_tools(cursor=cursor)
        descriptors.extend(page.tools)
        next_cursor = page.next_cursor
        if next_cursor is None:
            break
        if next_cursor in seen_cursors:
            raise McpToolDiscoveryError("MCP discovery cursor cycle detected")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    by_name: dict[str, McpToolDescriptor] = {}
    for descriptor in descriptors:
        if descriptor.name in by_name:
            raise McpToolDiscoveryError(
                f"MCP server exposed a duplicate tool name: {descriptor.name}"
            )
        by_name[descriptor.name] = descriptor

    pending: list[tuple[ToolDefinition, McpToolAdapter]] = []
    seen_bindings: set[str] = set()
    for binding in bindings:
        if binding.remote_name in seen_bindings:
            raise McpToolDiscoveryError(
                f"allowlist repeats remote tool: {binding.remote_name}"
            )
        seen_bindings.add(binding.remote_name)

        descriptor = by_name.get(binding.remote_name)
        if descriptor is None:
            raise McpToolDiscoveryError(
                f"allowlisted MCP tool not found: {binding.remote_name}"
            )

        _check_object_schema(
            descriptor.input_schema,
            label="input",
            tool_name=binding.remote_name,
        )
        if descriptor.output_schema is not None:
            _check_schema(
                descriptor.output_schema,
                label="output",
                tool_name=binding.remote_name,
            )

        actual_input_hash = canonical_schema_hash(descriptor.input_schema)
        if actual_input_hash != binding.expected_input_schema_sha256:
            raise McpToolDiscoveryError(
                f"input schema hash mismatch for {binding.remote_name}: "
                f"expected={binding.expected_input_schema_sha256}, "
                f"actual={actual_input_hash}"
            )
        if binding.expected_output_schema_sha256 is not None:
            if descriptor.output_schema is None:
                raise McpToolDiscoveryError(
                    f"output schema missing for {binding.remote_name}"
                )
            actual_output_hash = canonical_schema_hash(descriptor.output_schema)
            if actual_output_hash != binding.expected_output_schema_sha256:
                raise McpToolDiscoveryError(
                    f"output schema hash mismatch for {binding.remote_name}: "
                    f"expected={binding.expected_output_schema_sha256}, "
                    f"actual={actual_output_hash}"
                )

        qualified_name = f"mcp.{server_id}.{binding.remote_name}"
        try:
            registry.resolve(qualified_name)
        except UnknownToolError:
            pass
        else:
            raise McpToolDiscoveryError(
                f"MCP tool conflicts with an existing registration: "
                f"{qualified_name}"
            )

        definition = ToolDefinition(
            name=qualified_name,
            description=binding.local_description,
            capability=binding.capability,
            input_model=_arguments_model(
                qualified_name,
                descriptor.input_schema,
            ),
        )
        pending.append((definition, McpToolAdapter(transport, descriptor)))

    for definition, adapter in pending:
        registry.register(definition, adapter)

    return tuple(definition.name for definition, _ in pending)


def _check_object_schema(
    schema: dict[str, JsonValue],
    *,
    label: str,
    tool_name: str,
) -> None:
    _check_schema(schema, label=label, tool_name=tool_name)
    if schema.get("type") != "object":
        raise McpToolDiscoveryError(
            f"MCP tool {tool_name!r} has invalid {label} schema: "
            "the root type must be object"
        )


def _check_schema(
    schema: dict[str, JsonValue],
    *,
    label: str,
    tool_name: str,
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise McpToolDiscoveryError(
            f"MCP tool {tool_name!r} has invalid {label} schema"
        ) from exc
