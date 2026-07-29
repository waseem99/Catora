# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from catora_api.schemas.service_visibility import ServicePageSnapshot


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.headings: list[str] = []
        self.links: list[str] = []
        self.json_ld: list[dict[str, object]] = []
        self.meta_description: str | None = None
        self.canonical: str | None = None
        self.robots: list[str] = []
        self.author: str | None = None
        self._stack: list[str] = []
        self._capture_json = False
        self._json_parts: list[str] = []
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        self._stack.append(tag)
        if tag == "a" and values.get("href"):
            self.links.append(urljoin(self.base_url, values["href"]))
        if tag == "link" and "canonical" in values.get("rel", "").casefold():
            self.canonical = urljoin(self.base_url, values.get("href", ""))
        if tag == "meta":
            name = values.get("name", "").casefold()
            prop = values.get("property", "").casefold()
            content = values.get("content", "").strip()
            if name == "description" or prop == "og:description":
                self.meta_description = self.meta_description or content
            elif name == "robots":
                self.robots.extend(part.strip() for part in content.split(","))
            elif name == "author":
                self.author = content or self.author
        if tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._capture_json = True
            self._json_parts = []
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture_json:
            self._capture_json = False
            raw = "".join(self._json_parts).strip()
            try:
                value = json.loads(raw)
                blocks = value if isinstance(value, list) else [value]
                self.json_ld.extend(block for block in blocks if isinstance(block, dict))
            except json.JSONDecodeError:
                pass
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading = " ".join("".join(self._heading_parts).split())
            if heading:
                self.headings.append(heading)
            self._heading_parts = []
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._capture_json:
            self._json_parts.append(data)
            return
        current = self._stack[-1] if self._stack else ""
        if current in {"script", "style", "noscript", "svg"}:
            return
        if current == "title":
            self.title_parts.append(data)
        if current in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_parts.append(data)
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)


def extract_page(url: str, html: str, *, status_code: int = 200) -> ServicePageSnapshot:
    parser = _PageParser(url)
    parser.feed(html)
    parsed = urlparse(url)
    internal = sorted({
        link.split("#", 1)[0]
        for link in parser.links
        if urlparse(link).hostname == parsed.hostname and urlparse(link).scheme in {"http", "https"}
    })
    title = " ".join("".join(parser.title_parts).split())
    text = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()
    canonical = parser.canonical or url
    digest = hashlib.sha256(
        "\n".join((canonical, title, parser.meta_description or "", text)).encode()
    ).hexdigest()
    return ServicePageSnapshot.model_validate(
        {
            "id": canonical,
            "url": url,
            "canonicalUrl": canonical,
            "statusCode": status_code,
            "title": title,
            "metaDescription": parser.meta_description,
            "h1": parser.headings[0] if parser.headings else None,
            "headings": parser.headings,
            "visibleText": text[:250_000],
            "internalLinks": internal[:5_000],
            "structuredData": parser.json_ld[:200],
            "author": parser.author,
            "robots": parser.robots,
            "contentHash": digest,
        }
    )
