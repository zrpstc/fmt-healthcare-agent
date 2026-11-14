"""Optional bounded SearXNG adapter. Retrieved pages are untrusted evidence data."""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import os
from urllib.parse import urlsplit

import httpx

DOMAINS = (
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
    "lpsn.dsmz.de", "bacdive.dsmz.de", "nature.com", "cell.com", "journals.asm.org",
    "frontiersin.org", "microbiomejournal.biomedcentral.com", "academic.oup.com",
)
WIKIPEDIA = ("zh.wikipedia.org", "en.wikipedia.org")
MAX_BYTES = 262144
TIMEOUT = 5


def allowed_url(value):
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        return (url.scheme == "https" and not url.username and not url.password
                and (host in WIKIPEDIA or any(host == d or host.endswith("." + d) for d in DOMAINS)))
    except (ValueError, TypeError):
        return False


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _body(client, url):
    for _ in range(4):
        if not allowed_url(url):
            return ""
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers.get("location", "")))
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", "").lower():
                return ""
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    return ""
            parser = _Text()
            parser.feed(raw.decode("utf-8", errors="replace"))
            return " ".join(" ".join(parser.parts).split())[:4000]
    return ""


def search(term, *, client=None):
    if os.environ.get("WGS_WEB_SEARCH_PROVIDER", "").lower() != "searxng":
        return []
    base = os.environ.get("WGS_SEARXNG_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return []
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        with client.stream("GET", base + "/search", params={"q": term, "format": "json"}) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    return []
        import json
        results = json.loads(raw).get("results", [])
        results = [r for r in results if isinstance(r, dict) and allowed_url(r.get("url", ""))]
        results.sort(key=lambda r: urlsplit(r["url"]).hostname in WIKIPEDIA)
        output = []
        for row in results[:3]:
            try:
                excerpt = _body(client, row["url"])
                if excerpt:
                    output.append({"type": "web", "id_or_url": row["url"], "title": str(row.get("title", ""))[:240],
                                   "year": None, "accessed_at": datetime.now(timezone.utc).date().isoformat(),
                                   "text": excerpt, "evidence_scope": "genus"})
            except (httpx.HTTPError, ValueError, TypeError):
                continue
        return output
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return []
    finally:
        if owned:
            client.close()
