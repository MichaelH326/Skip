import httpx
import pytest

from adpress import fetcher
from adpress.fetcher import Fetcher, FetchError

PAGES = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private"),
    "/": ("text/html", """<html><head><title>Harbor Realty</title>
        <meta name="description" content="Tacoma homes since 2004">
        <meta name="theme-color" content="#0B3D5C">
        <link rel="stylesheet" href="/site.css">
        <style>h1 { color: #FF6600; font-family: 'Playfair Display', serif; }</style></head>
        <body><h1>Find your home</h1><p>Serving Tacoma since 2004.</p>
        <a href="/about">About</a><a href="/private/x">Private</a><a href="https://other.example/">Other</a>
        <script>var x = "#000000";</script></body></html>"""),
    "/about": ("text/html", "<html><body><h2>About us</h2><p>Local agents who know every street.</p></body></html>"),
    "/site.css": ("text/css", "body { color: #333333; background: #FFFFFF; font-family: Inter, sans-serif; } a { color: #1A7F5A }"),
}


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host != "harbor.example":
        return httpx.Response(500)
    ct, body = PAGES.get(request.url.path, ("text/html", None))
    if body is None:
        return httpx.Response(404, text="nope")
    return httpx.Response(200, text=body, headers={"content-type": ct})


@pytest.fixture(autouse=True)
def public_hosts(monkeypatch):
    monkeypatch.setattr(fetcher, "_check_host_is_public", lambda host: None)


def test_fetch_site_extracts_text_colors_fonts():
    f = Fetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    site = f.fetch_site("harbor.example")
    urls = [p.url for p in site.pages]
    assert urls == ["https://harbor.example", "https://harbor.example/about"]
    assert "Serving Tacoma since 2004." in site.pages[0].text
    assert "Tacoma homes since 2004" in site.pages[0].text
    assert "var x" not in site.pages[0].text
    assert site.colors[0] == "#0B3D5C"
    assert set(site.colors) == {"#0B3D5C", "#FF6600", "#1A7F5A"}
    assert site.fonts[:2] == ["Playfair Display", "Inter"] or set(site.fonts) >= {"Playfair Display", "Inter"}


def test_empty_site_raises():
    f = Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    with pytest.raises(FetchError):
        f.fetch_site("https://harbor.example")


def test_private_addresses_blocked(monkeypatch):
    monkeypatch.undo()
    with pytest.raises(FetchError, match="private network"):
        fetcher._check_host_is_public("127.0.0.1")


def test_bad_url():
    with pytest.raises(FetchError):
        fetcher.normalize_url("ftp://x")
