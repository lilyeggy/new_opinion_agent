import ipaddress
import re
import socket
from urllib.parse import (
    SplitResult,
    quote_from_bytes,
    unquote_to_bytes,
    urlsplit,
    urlunsplit,
)


class InvalidPublicUrl(ValueError):
    """Raised when a URL is outside the supported public Web boundary."""


def normalize_secure_provider_endpoint(url: str) -> str:
    normalized = normalize_public_url(url)
    if urlsplit(normalized).scheme != "https":
        raise InvalidPublicUrl("provider endpoints must use HTTPS")
    return normalized


def normalize_public_url(url: str) -> str:
    candidate = url
    if not candidate or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in candidate
    ):
        raise InvalidPublicUrl("URL must not contain whitespace or control characters")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise InvalidPublicUrl("URL authority is invalid") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidPublicUrl("only HTTP and HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidPublicUrl("credential-bearing URLs are not supported")
    if parsed.hostname is None:
        raise InvalidPublicUrl("URL requires a hostname")

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise InvalidPublicUrl("local hostnames are not public URLs")

    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = _parse_legacy_ipv4_literal(hostname)
    if literal_address is not None and not literal_address.is_global:
        raise InvalidPublicUrl("non-public IP addresses are not supported")

    ascii_hostname = hostname.encode("idna").decode("ascii")
    if literal_address is not None and literal_address.version == 6:
        rendered_hostname = f"[{ascii_hostname}]"
    else:
        rendered_hostname = ascii_hostname

    is_default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = rendered_hostname
    if port is not None and not is_default_port:
        netloc = f"{rendered_hostname}:{port}"

    normalized = SplitResult(
        scheme=scheme,
        netloc=netloc,
        path=_encode_url_component(
            parsed.path or "/",
            safe="/:@-._~!$&'*,;=",
        ),
        query=_encode_url_component(
            parsed.query,
            safe="=&/:?@-._~!$'*,;+",
        ),
        fragment="",
    )
    return urlunsplit(normalized)


def _encode_url_component(value: str, *, safe: str) -> str:
    return quote_from_bytes(unquote_to_bytes(value), safe=safe)


def _parse_legacy_ipv4_literal(
    hostname: str,
) -> ipaddress.IPv4Address | None:
    if re.fullmatch(r"[0-9A-Fa-fxX.]+", hostname) is None:
        return None
    try:
        packed = socket.inet_aton(hostname)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)
