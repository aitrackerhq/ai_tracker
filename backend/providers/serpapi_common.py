"""Shared parsing for SerpAPI responses that carry `text_blocks` + `references`
(Google AI Overview and Google AI Mode share this shape)."""
from __future__ import annotations

from typing import Any

from backend.utils.helpers import collapse_ws, domain_from_url


def flatten_text_blocks(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(_render(blocks)).strip()


def _render(blocks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for block in blocks or []:
        btype = block.get("type", "")
        snippet = collapse_ws(block.get("snippet") or "")
        if btype == "list":
            for item in block.get("list") or []:
                title = collapse_ws(item.get("title") or "")
                isnip = collapse_ws(item.get("snippet") or "")
                line = ": ".join(x for x in (title, isnip) if x)
                if line:
                    out.append(f"• {line}")
                nested_item = item.get("text_blocks")
                if nested_item:
                    out.extend(_render(nested_item))
        elif snippet:
            out.append(snippet)
        if btype != "list":
            nested = block.get("text_blocks")
            if nested:
                out.extend(_render(nested))
    return out


def extract_references(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Citations live in `references`; fall back to `sources` for older shapes."""
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    refs = container.get("references") or container.get("sources") or []
    for ref in refs:
        url = ref.get("link") or ref.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        citations.append(
            {
                "title": ref.get("title") or "",
                "url": url,
                "domain": domain_from_url(url),
                "source": ref.get("source") or "",
            }
        )
    return citations
