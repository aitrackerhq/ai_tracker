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
_BOLD_RE = re.compile(r"\*\*([A-Z][^*\n]{1,60}?)\*\*")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+([A-Z][\w&\-\. ]{1,60})")
# Include •, –, ● as bullet markers (SerpAPI AI Overview/Mode use "• " prefixes)
_LIST_BRAND_RE = re.compile(
    r"(?m)^\s*(?:\d+\.|[-*•●–])\s+\*?\*?([A-Z][\w&\-\. ]{1,60}?)\*?\*?(?=[\s:—–\-]|$)"
)

# Leading/trailing junk to strip from entity text (bullets, list markers, punctuation)
_STRIP_CHARS = " \t\r\n.,;:!?\"'()[]{}*_•●–—-"
_WS_RE = re.compile(r"\s+")

# Common all-caps acronyms that are NOT brands. Short all-caps tokens are dropped
# unless allow-listed as a real brand.
_ALLCAPS_BRANDS = {"AWS", "IBM", "SAP", "GCP", "SAS", "AMD", "HP", "GE", "ZOHO"}


@lru_cache(maxsize=1)
def _stopwords() -> set[str]:
    return {
        "best", "top", "alternatives", "alternative", "software", "tools", "tool",
        "platform", "platforms", "documentation", "knowledge", "management",
        "project", "collaboration", "startup", "guide", "review", "overview",
        "introduction", "summary", "comparison", "options", "option", "features",
        "feature", "pricing", "conclusion", "ai", "the", "and", "or", "for",
        "with", "you", "your", "pros", "cons", "key", "takeaways",
        # question / auxiliary / pronoun words that get capitalised at sentence start
        "what", "when", "where", "why", "how", "who", "which", "are", "is", "do",
        "does", "can", "should", "will", "would", "this", "that", "these", "those",
        "here", "there", "it", "they", "we", "i", "a", "an", "to", "of", "in", "on",
        "if", "but", "however", "also", "best-known", "overall",
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
        # collapse internal whitespace/newlines, strip bullets + punctuation
        s = _WS_RE.sub(" ", (s or "").replace("\n", " ")).strip()
        s = s.strip(_STRIP_CHARS).strip()
        # comma-joined lists ("Windows, Mac, Linux") → keep the first real name
        if "," in s:
            s = s.split(",", 1)[0].strip()
        # drop possessive ("Notion's" -> "Notion")
        s = re.sub(r"['’]s$", "", s).strip()
        if len(s) < 2 or len(s) > 60:
            return None
        if len(s.split()) > 5:  # brands are short; long phrases are headings/noise
            return None
        if s.lower() in _stopwords():
            return None
        # reject phrases made entirely of generic/stopwords (e.g. headings)
        words = s.split()
        if len(words) > 1 and all(w.lower().strip("&-.") in _stopwords() for w in words):
            return None
        if not re.search(r"[A-Za-z]", s):
            return None
        # drop short all-caps acronyms (ETL, ELT, CDC, API, SQL, KPI...) unless a known brand
        if s.isalpha() and s.isupper() and 2 <= len(s) <= 4 and s not in _ALLCAPS_BRANDS:
            return None
        return s
