import pytest

from opinion_search.tools.url import InvalidPublicUrl, normalize_public_url


def test_normalize_public_url_canonicalizes_identity_fields() -> None:
    assert (
        normalize_public_url("HTTPS://Example.COM:443/path?q=One#fragment")
        == "https://example.com/path?q=One"
    )
    assert normalize_public_url("http://Example.COM:80") == ("http://example.com/")
    assert normalize_public_url("https://example.com/a(b)/报道?q=(one%20two)") == (
        "https://example.com/a%28b%29/%E6%8A%A5%E9%81%93?q=%28one%20two%29"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/private",
        "ftp://example.com/file",
        "https://user:secret@example.com/",
        "https://localhost/page",
        "https://127.0.0.1/page",
        "https://127.1/page",
        "https://2130706433/page",
        "https://0x7f000001/page",
        "https://10.0.0.1/page",
        "https://[::1]/page",
        "https:///missing-host",
        " https://example.com/path",
        "https://example.com/a b",
        "https://example.com/a\nheader",
    ],
)
def test_normalize_public_url_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(InvalidPublicUrl):
        normalize_public_url(url)
