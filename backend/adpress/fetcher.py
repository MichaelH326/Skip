"""Fetch a brand's public website and extract copy, colors, and fonts (PRD: Import from website URL)."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .config import settings

MAX_PAGE_BYTES = 2_000_000
MAX_CSS_FILES = 4
PRIORITY_WORDS = ("about", "service", "team", "why", "story", "mission", "listing", "product", "pricing", "contact")
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "inherit", "initial", "cursive", "-apple-system",
                  "blinkmacsystemfont", "ui-sans-serif", "ui-serif", "ui-monospace", "var", "unset"}


class FetchError(Exception):
    pass


@dataclass
class Page:
    url: str
    title: str
    text: str


@dataclass
class SiteExtract:
    url: str
    pages: list[Page] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    url = url.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) and not re.match(r"^https?://", url, re.I):
        raise FetchError("Enter a website address that starts with http or https.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Enter a valid website address, like example.com.")
    return url


def _check_host_is_public(host: str) -> None:
    if settings.fetch_allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise FetchError(f"Could not find the website {host}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise FetchError("That address points to a private network and cannot be fetched.")


def _same_site(host_a: str, host_b: str) -> bool:
    strip = lambda h: h.lower().removeprefix("www.")  # noqa: E731
    return strip(host_a) == strip(host_b)


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    parts: list[str] = []
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        parts.append(str(meta["content"]).strip())
    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if len(text) >= 3:
            parts.append(text)
    # Drop exact duplicates (menus and footers repeat across pages).
    return "\n".join(dict.fromkeys(parts))


def _is_neutral(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) < 16  # greys, black, white


def _normalize_hex(c: str) -> str:
    h = c.lstrip("#").upper()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h


def _fonts_from_css(css: str) -> list[str]:
    fonts: list[str] = []
    for decl in _FONT_RE.findall(css):
        for name in decl.split(","):
            name = name.strip().strip("'\"").strip()
            if name and name.lower() not in _GENERIC_FONTS and not name.lower().startswith("var("):
                fonts.append(name)
    return fonts


class Fetcher:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
        )

    def _get(self, url: str) -> httpx.Response:
        """GET with manual redirects so every hop is checked against private networks."""
        for _ in range(5):
            host = urlparse(url).hostname or ""
            _check_host_is_public(host)
            resp = self.client.get(url)
            if resp.is_redirect and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                continue
            return resp
        raise FetchError("The website redirected too many times.")

    def _robots(self, base: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            resp = self._get(urljoin(base, "/robots.txt"))
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except (httpx.HTTPError, FetchError):
            rp.parse([])
        return rp

    def fetch_site(self, url: str) -> SiteExtract:
        start = time.monotonic()
        url = normalize_url(url)
        root_host = urlparse(url).hostname or ""
        robots = self._robots(url)
        out = SiteExtract(url=url)
        queue: list[str] = [url]
        seen: set[str] = set()
        css_urls: list[str] = []
        colors: Counter[str] = Counter()
        fonts: Counter[str] = Counter()

        while queue and len(out.pages) < settings.fetch_max_pages:
            if time.monotonic() - start > settings.fetch_timeout_s:
                out.errors.append("Stopped early: the website was slow to respond.")
                break
            page_url = queue.pop(0)
            if page_url in seen:
                continue
            seen.add(page_url)
            if not robots.can_fetch(settings.user_agent, page_url):
                out.errors.append(f"Skipped {page_url}: disallowed by robots.txt")
                continue
            try:
                resp = self._get(page_url)
            except (httpx.HTTPError, FetchError) as e:
                out.errors.append(f"Could not fetch {page_url}: {e}")
                continue
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "html"):
                out.errors.append(f"Could not fetch {page_url}: HTTP {resp.status_code}")
                continue
            html = resp.text[:MAX_PAGE_BYTES]
            soup = BeautifulSoup(html, "html.parser")

            for style in soup.find_all("style"):
                css = style.get_text()
                colors.update(_normalize_hex(c) for c in _HEX_RE.findall(css))
                fonts.update(_fonts_from_css(css))
            for el in soup.find_all(style=True):
                colors.update(_normalize_hex(c) for c in _HEX_RE.findall(el["style"]))
                fonts.update(_fonts_from_css(el["style"]))
            theme = soup.find("meta", attrs={"name": "theme-color"})
            if theme and theme.get("content") and _HEX_RE.fullmatch(str(theme["content"]).strip()):
                colors[_normalize_hex(str(theme["content"]).strip())] += 5
            for link in soup.find_all("link", rel=lambda r: r and "stylesheet" in r):
                href = link.get("href")
                if href:
                    css_url = urljoin(page_url, href)
                    if css_url not in css_urls and _same_site(urlparse(css_url).hostname or "", root_host):
                        css_urls.append(css_url)

            links: list[str] = []
            for a in soup.find_all("a", href=True):
                link = urldefrag(urljoin(page_url, a["href"]))[0]
                parsed = urlparse(link)
                if parsed.scheme in ("http", "https") and _same_site(parsed.hostname or "", root_host):
                    if not re.search(r"\.(pdf|jpg|jpeg|png|gif|zip|mp4|webp|svg)$", parsed.path, re.I):
                        links.append(link)
            links.sort(key=lambda link: 0 if any(w in link.lower() for w in PRIORITY_WORDS) else 1)
            queue.extend(link for link in links if link not in seen and link not in queue)

            title = soup.title.get_text(strip=True) if soup.title else page_url
            text = _visible_text(soup)
            if text:
                out.pages.append(Page(url=page_url, title=title, text=text))

        for css_url in css_urls[:MAX_CSS_FILES]:
            if time.monotonic() - start > settings.fetch_timeout_s:
                break
            try:
                resp = self._get(css_url)
                if resp.status_code == 200:
                    css = resp.text[:MAX_PAGE_BYTES]
                    colors.update(_normalize_hex(c) for c in _HEX_RE.findall(css))
                    fonts.update(_fonts_from_css(css))
            except (httpx.HTTPError, FetchError):
                continue

        out.colors = [c for c, _ in colors.most_common() if not _is_neutral(c)][:6]
        out.fonts = [f for f, _ in fonts.most_common(4)]
        if not out.pages:
            raise FetchError(
                "No readable content was found on that website. "
                "You can still set up the kit by pasting your content manually."
                + (f" Details: {out.errors[0]}" if out.errors else "")
            )
        return out
