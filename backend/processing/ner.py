from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

# Lazy spaCy: NER is only needed during processing and can be slow to import.
_NLP = None


def _get_nlp():
    global _NLP
    if _NLP is not None:
        return _NLP
    try:
        import spacy

        try:
            _NLP = spacy.load("en_core_web_sm", disable=["parser", "tagger", "lemmatizer"])
        except OSError:
            logger.warning(
                "spaCy model en_core_web_sm not installed. Run: python -m spacy download en_core_web_sm"
            )
            _NLP = spacy.blank("en")
    except Exception:
        logger.exception("spaCy unavailable; falling back to regex-only extraction")
        _NLP = False
    return _NLP


@dataclass(frozen=True)
class RawEntity:
    text: str
    label: str
    start: int


# Markdown-bold and Title-Case heuristics used as fallback when spaCy misses brand names
_BOLD_RE = re.compile(r"\*\*([A-Z][^*]{1,60}?)\*\*")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+([A-Z][\w&\-\. ]{1,60})")
_LIST_BRAND_RE = re.compile(r"(?m)^\s*(?:\d+\.|[-*])\s+\*?\*?([A-Z][\w&\-\. ]{1,60}?)\*?\*?(?=[\s:—–\-])")


@lru_cache(maxsize=1)
def _stopwords() -> set[str]:
    return {
        "best", "top", "alternatives", "software", "tools", "platform", "platforms",
        "documentation", "knowledge", "management", "project", "collaboration",
        "startup", "guide", "review", "overview", "introduction", "summary",
        "ai", "the", "and", "or", "for", "with", "you", "your",
    }


class EntityExtractor:
    """Hybrid extractor: spaCy NER + ordered regex fallbacks. Preserves first-mention order."""

    ENTITY_LABELS = {"ORG", "PRODUCT", "WORK_OF_ART"}

    def extract(self, text: str) -> list[RawEntity]:
        if not text:
            return []
        seen: dict[str, RawEntity] = {}
        order: list[str] = []

        nlp = _get_nlp()
        if nlp and nlp is not False:
            try:
                doc = nlp(text[:20000])
                for ent in doc.ents:
                    if ent.label_ not in self.ENTITY_LABELS:
                        continue
                    cleaned = self._clean(ent.text)
                    if not cleaned:
                        continue
                    key = cleaned.lower()
                    if key not in seen:
                        seen[key] = RawEntity(text=cleaned, label=ent.label_, start=ent.start_char)
                        order.append(key)
            except Exception:
                logger.exception("spaCy NER failed")

        for pattern, label in (
            (_BOLD_RE, "BOLD"),
            (_HEADING_RE, "HEADING"),
            (_LIST_BRAND_RE, "LIST"),
        ):
            for m in pattern.finditer(text):
                cleaned = self._clean(m.group(1))
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key not in seen:
                    seen[key] = RawEntity(text=cleaned, label=label, start=m.start(1))
                    order.append(key)

        return [seen[k] for k in sorted(order, key=lambda k: seen[k].start)]

    def _clean(self, s: str) -> str | None:
        s = (s or "").strip(" \t.,;:!?\"'()[]{}*_")
        if len(s) < 2 or len(s) > 80:
            return None
        if s.lower() in _stopwords():
            return None
        if not re.search(r"[A-Za-z]", s):
            return None
        return s
