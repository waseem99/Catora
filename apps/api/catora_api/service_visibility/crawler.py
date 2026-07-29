# ruff: noqa: E501
from __future__ import annotations

import asyncio
import ipaddress
import socket
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from catora_api.schemas.service_visibility import ServicePageSnapshot
from catora_api.service_visibility.extraction import extract_page

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_SITEMAPS = 10
_USER_AGENT = "Catora-Service-Visibility/1.0"


@dataclass(frozen=True, slots=True)
class _Fetched:
    status_code: int
    headers: httpx.Headers
    content: bytes
    encoding: str | None


async def _public_host(host: str) -> None:
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, None)
    if not addresses:
        raise ValueError("Service visibility crawl target did not resolve")
    for address in addresses:
        value = ipaddress.ip_address(address[4][0])
        if (
            value.is_private
            or value.is_loopback
            or value.is_link_local
            or value.is_reserved
            or value.is_multicast
            or value.is_unspecified
        ):
            raise ValueError("Service visibility crawl target must resolve only to public addresses")


def _same_host(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname == host


async def _fetch_limited(
    client: httpx.AsyncClient,
    *,
    url: str,
    host: str,
) -> _Fetched:
    if not _same_host(url, host):
        raise ValueError("Crawl request left the authorized host")
    await _public_host(host)
    try:
        async with client.stream("GET", url) as response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise ValueError("Crawl response exceeded the configured size limit")
                chunks.append(chunk)
            return _Fetched(
                status_code=response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                encoding=response.encoding,
            )
    except httpx.HTTPError as exc:
        raise ValueError("Crawl request failed") from exc


def _xml_locations(content: bytes) -> tuple[str, ...]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return ()
    return tuple(
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "loc" and (element.text or "").strip()
    )


async def _discover_sitemap_pages(
    client: httpx.AsyncClient,
    *,
    start_url: str,
    host: str,
    robots_text: str,
    max_pages: int,
) -> tuple[str, ...]:
    candidates = [
        line.split(":", 1)[1].strip()
        for line in robots_text.splitlines()
        if line.casefold().startswith("sitemap:") and ":" in line
    ]
    candidates.extend(
        urljoin(start_url, path)
        for path in ("/wp-sitemap.xml", "/sitemap_index.xml", "/sitemap.xml")
    )
    sitemap_queue: deque[str] = deque(url for url in candidates if _same_host(url, host))
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []
    while sitemap_queue and len(seen_sitemaps) < _MAX_SITEMAPS and len(page_urls) < max_pages:
        sitemap_url = sitemap_queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            response = await _fetch_limited(client, url=sitemap_url, host=host)
        except ValueError:
            continue
        if response.status_code != 200:
            continue
        for location in _xml_locations(response.content):
            if not _same_host(location, host):
                continue
            if location.casefold().endswith(".xml"):
                sitemap_queue.append(location)
            elif location not in page_urls:
                page_urls.append(location)
                if len(page_urls) >= max_pages:
                    break
    return tuple(page_urls)


async def crawl_site(start_url: str, *, max_pages: int = 150) -> tuple[ServicePageSnapshot, ...]:
    parsed = urlparse(start_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A public HTTP(S) start URL is required")
    host = parsed.hostname
    await _public_host(host)
    queue: deque[str] = deque([start_url])
    seen: set[str] = set()
    pages: list[ServicePageSnapshot] = []
    robots = RobotFileParser()
    robots_url = urljoin(start_url, "/robots.txt")
    robots.set_url(robots_url)
    robots_text = ""
    robots_loaded = False
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        follow_redirects=False,
        headers={"User-Agent": _USER_AGENT},
        trust_env=False,
    ) as client:
        try:
            response = await _fetch_limited(client, url=robots_url, host=host)
            if response.status_code == 200:
                robots_text = response.content.decode("utf-8", errors="replace")
                robots.parse(robots_text.splitlines())
                robots_loaded = True
        except ValueError:
            pass
        queue.extend(
            await _discover_sitemap_pages(
                client,
                start_url=start_url,
                host=host,
                robots_text=robots_text,
                max_pages=max_pages,
            )
        )
        while queue and len(pages) < max_pages:
            url = queue.popleft().split("#", 1)[0]
            if url in seen or not _same_host(url, host):
                continue
            seen.add(url)
            if robots_loaded and not robots.can_fetch(_USER_AGENT, url):
                continue
            try:
                response = await _fetch_limited(client, url=url, host=host)
            except ValueError:
                continue
            if 300 <= response.status_code < 400:
                target = urljoin(url, response.headers.get("location", ""))
                if not _same_host(target, host):
                    raise ValueError("Crawl redirect left the authorized host")
                queue.append(target)
                continue
            content_type = response.headers.get("content-type", "").casefold()
            if response.status_code >= 400 or "text/html" not in content_type:
                continue
            html = response.content.decode(response.encoding or "utf-8", errors="replace")
            page = extract_page(url, html, status_code=response.status_code)
            if not _same_host(str(page.canonical_url), host):
                raise ValueError("Page canonical left the authorized host")
            pages.append(page)
            queue.extend(str(link) for link in page.internal_links if str(link) not in seen)
            await asyncio.sleep(0.1)
    return tuple(pages)
