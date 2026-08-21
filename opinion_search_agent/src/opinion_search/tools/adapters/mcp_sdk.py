"""Official MCP Python SDK v2 transport adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, TypeAlias
from urllib.parse import urlsplit

import httpx2

from mcp import (
    Client,
    StdioServerParameters,
    stdio_client,
)
from mcp.client.streamable_http import streamable_http_client
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_core import PydanticSerializationError

from opinion_search.tools.adapters.mcp import (
    McpCallResult,
    McpListToolsResult,
    McpToolDescriptor,
    McpToolDiscoveryError,
)
from opinion_search.tools.contracts import (
    ToolAdapterError,
    ToolErrorKind,
)
from opinion_search.tools.url import (
    InvalidPublicUrl,
    normalize_secure_provider_endpoint,
)


NonEmptyText = Annotated[str, Field(min_length=1)]


class McpStdioConfig(BaseModel):
    """Stdio transport config owned by app composition, never Domain State."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["stdio"] = "stdio"
    command: NonEmptyText
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    # Only these explicitly named entries reach the child; the process
    # environment is never inherited as a whole.
    env: dict[str, SecretStr] = {}


class McpHttpConfig(BaseModel):
    """Streamable HTTP transport config owned by app composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Literal["streamable_http"] = "streamable_http"
    url: NonEmptyText
    headers: dict[str, SecretStr] = {}
    allow_insecure_loopback: bool = False

    @model_validator(mode="after")
    def validate_endpoint_security(self) -> McpHttpConfig:
        url = self.url
        if not url or any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            for character in url
        ):
            raise ValueError(
                "MCP HTTP endpoint must not contain whitespace or control characters"
            )
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise ValueError("MCP HTTP endpoint authority is invalid") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("MCP HTTP endpoint must not contain userinfo")
        if parsed.hostname is None:
            raise ValueError("MCP HTTP endpoint requires a hostname")
        host = parsed.hostname.casefold().rstrip(".")
        scheme = parsed.scheme.casefold()

        if self.allow_insecure_loopback:
            if scheme != "http":
                raise ValueError(
                    "insecure loopback allowance requires plain HTTP"
                )
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(
                    "insecure development allowance is loopback-only"
                )
            return self

        try:
            normalize_secure_provider_endpoint(url)
        except InvalidPublicUrl as exc:
            raise ValueError(
                "MCP HTTP endpoint must be a normalized public HTTPS URL"
            ) from exc
        return self


McpSdkConfig: TypeAlias = Annotated[
    McpStdioConfig | McpHttpConfig,
    Field(discriminator="transport"),
]


class SdkMcpTransport:
    """Transport that opens an official SDK v2 client per list/call operation.

    Deliberately stateless and read-only: each ``list_tools`` and ``call_tool``
    opens a client context, performs one operation, and closes it. Stateful
    session reuse between calls is not supported. SDK connection/protocol
    errors are normalized into a safe discovery error or ToolAdapterError; no
    command env, headers, response body or exception repr is ever included.
    """

    def __init__(self, config: McpSdkConfig) -> None:
        self._config = config

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
    ) -> McpListToolsResult:
        try:
            async with self._client() as client:
                result = await client.list_tools(cursor=cursor)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise McpToolDiscoveryError(
                "MCP discovery failed against the configured server."
            ) from exc
        return McpListToolsResult(
            tools=tuple(self._map_tool(tool) for tool in result.tools),
            next_cursor=result.next_cursor,
        )

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpCallResult:
        try:
            async with self._client() as client:
                result = await client.call_tool(name, dict(arguments))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ToolAdapterError(
                ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                "The MCP server call failed.",
            ) from exc
        return McpCallResult(
            content=tuple(_dump_content(block) for block in result.content),
            structured_content=result.structured_content,
            is_error=result.is_error,
        )

    @staticmethod
    def _map_tool(tool) -> McpToolDescriptor:
        return McpToolDescriptor(
            name=tool.name,
            description=(tool.description or "No remote description provided."),
            input_schema=tool.input_schema,
            output_schema=getattr(tool, "output_schema", None),
            annotations=getattr(tool, "annotations", None),
        )

    @asynccontextmanager
    async def _client(self):
        config = self._config
        if isinstance(config, McpStdioConfig):
            params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                cwd=config.cwd,
                env={
                    key: value.get_secret_value()
                    for key, value in config.env.items()
                },
            )
            transport = stdio_client(params)
            async with Client(transport) as client:
                yield client
            return

        endpoint = config.url
        if not config.allow_insecure_loopback:
            try:
                endpoint = normalize_secure_provider_endpoint(config.url)
            except InvalidPublicUrl as exc:
                raise ToolAdapterError(
                    ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
                    "The MCP HTTP endpoint is not a valid public HTTPS URL.",
                ) from exc
        headers = {
            key: value.get_secret_value()
            for key, value in config.headers.items()
        }
        async with httpx2.AsyncClient(headers=headers) as http_client:
            transport = streamable_http_client(
                endpoint,
                http_client=http_client,
            )
            async with Client(transport) as client:
                yield client


_SDK_CONTENT_METADATA_KEYS = frozenset({"meta", "_meta", "annotations"})


class _ContentProjectionCycleError(ValueError):
    """Raised internally when remote content contains a reference cycle."""


def _dump_content(block: object) -> JsonValue:
    """Project one SDK content block to JSON without SDK metadata.

    Protocol metadata fields (``meta``, ``_meta``, ``annotations``) are
    removed recursively at every nesting level before validation, so remote
    metadata never reaches ToolResult or Context. Public content that is not
    JSON-representable raises a safe ToolAdapterError; no raw SDK/Pydantic
    exception, object repr or remote payload crosses this boundary.
    """
    try:
        return TypeAdapter(JsonValue).validate_python(
            _project_content_block(block)
        )
    except (
        ValidationError,
        PydanticSerializationError,
        _ContentProjectionCycleError,
        RecursionError,
    ) as exc:
        raise ToolAdapterError(
            ToolErrorKind.UNKNOWN_PROVIDER_ERROR,
            "The MCP server returned a non-JSON content block.",
        ) from exc


def _project_content_block(block: object) -> object:
    """Recursively project one content block without SDK metadata fields.

    Field values are read in Python mode and metadata keys are dropped by
    field name or alias at every nesting level, so metadata is removed before
    any serialization attempt. Unsupported objects are left untouched for the
    final JsonValue validation, which converts them into the safe
    ToolAdapterError raised by ``_dump_content``.
    """
    return _project_content_node(block, active_ids=set())


def _project_content_node(block: object, active_ids: set[int]) -> object:
    is_container = isinstance(block, (BaseModel, Mapping, list, tuple))
    if not is_container:
        return block

    block_id = id(block)
    if block_id in active_ids:
        raise _ContentProjectionCycleError
    active_ids.add(block_id)
    try:
        return _project_container(block, active_ids)
    finally:
        active_ids.remove(block_id)


def _project_container(block: object, active_ids: set[int]) -> object:
    if isinstance(block, BaseModel):
        projected: dict[str, object] = {}
        for name, field in type(block).model_fields.items():
            if _is_metadata_field(name, field):
                continue
            projected[name] = _project_content_node(
                getattr(block, name), active_ids
            )
        if block.__pydantic_extra__:
            for name, value in block.__pydantic_extra__.items():
                if name in _SDK_CONTENT_METADATA_KEYS:
                    continue
                projected[name] = _project_content_node(value, active_ids)
        return projected
    if isinstance(block, Mapping):
        return {
            name: _project_content_node(value, active_ids)
            for name, value in block.items()
            if name not in _SDK_CONTENT_METADATA_KEYS
        }
    if isinstance(block, (list, tuple)):
        return [_project_content_node(item, active_ids) for item in block]
    raise TypeError("content container classification is inconsistent")


def _is_metadata_field(name: str, field: FieldInfo) -> bool:
    if name in _SDK_CONTENT_METADATA_KEYS:
        return True
    for alias in (
        field.alias,
        field.validation_alias,
        field.serialization_alias,
    ):
        if isinstance(alias, str) and alias in _SDK_CONTENT_METADATA_KEYS:
            return True
    return False
