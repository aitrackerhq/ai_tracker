"""High-level LLM-powered analysis built on the Gemini client.

Scope: prompt suggestions + competitor detection. (Sentiment/framing is local —
see backend.processing.sentiment.)
"""
from __future__ import annotations

import logging

from backend.llm import gemini

logger = logging.getLogger(__name__)


async def suggest_prompts(
    domain: str,
    existing_prompts: list[str],
    competitors: list[str] | None = None,
    n: int = 8,
) -> list[str]:
    """Generate search prompts the brand SHOULD appear in but may not be tracking yet."""
    comp = ", ".join(competitors or []) or "unknown"
    existing = "\n".join(f"- {p}" for p in existing_prompts) or "(none yet)"
    prompt = f"""You are an AI-search visibility strategist.

Brand domain: {domain}
Known competitors: {comp}
Prompts already tracked:
{existing}

Infer the brand's industry and the buyer's journey. Suggest {n} NEW natural-language
search prompts a real user would type into ChatGPT / Gemini / Perplexity / Google AI
where this brand SHOULD ideally appear but might be missing. Focus on high-intent,
category, comparison, and alternative-seeking queries. Do NOT repeat the tracked prompts.
Do NOT include the brand name in the prompts (we want to test unaided visibility).

Return ONLY a JSON array of strings, e.g. ["best ...", "alternatives to ..."]."""
    try:
        data = await gemini.generate_json(prompt)
    except gemini.LLMUnavailable:
        logger.exception("suggest_prompts failed")
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen = {p.lower().strip() for p in existing_prompts}
    for item in data:
        s = str(item).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:n]


async def detect_competitors(
    domain: str,
    prompts: list[str],
    response_texts: list[str],
    known: list[str] | None = None,
    n: int = 12,
) -> list[dict[str, str]]:
    """Extract clean competitor brands from raw AI responses (replaces noisy NER).

    Returns a list of {"name", "reason"} dicts.
    """
    known_set = {k.lower() for k in (known or [])}
    corpus = "\n\n---\n\n".join(t[:2500] for t in response_texts if t.strip())[:18000]
    if not corpus:
        return []
    prompt_list = "\n".join(f"- {p}" for p in prompts) or "(none)"
    prompt = f"""You are analysing AI search answers to identify a brand's real competitors.

Target brand domain: {domain}
Search prompts used:
{prompt_list}

AI answers (multiple providers concatenated):
\"\"\"{corpus}\"\"\"

Identify the genuine COMPETITOR BRANDS/PRODUCTS that appear alongside the target brand
in these answers. Rules:
- Only real product/company names that compete with the target brand.
- Exclude the target brand itself, generic terms, feature names, categories, and noise.
- Normalise to the common brand name (e.g. "Notion AI" -> "Notion").
- Deduplicate.

Return ONLY a JSON array of objects: [{{"name": "Brand", "reason": "<=12 words why it's a competitor"}}]
Limit to the {n} most relevant."""
    try:
        data = await gemini.generate_json(prompt)
    except gemini.LLMUnavailable:
        logger.exception("detect_competitors failed")
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            reason = str(item.get("reason", "")).strip()
        else:
            name, reason = str(item).strip(), ""
        key = name.lower()
        if not name or key in seen or key in known_set:
            continue
        seen.add(key)
        out.append({"name": name, "reason": reason[:120]})
    return out[:n]
