"""Local sentiment + framing analysis (no external API).

Sentiment uses a HuggingFace model (default: cardiffnlp 3-class roberta) loaded
lazily on first use. If `transformers`/`torch` aren't installed, it falls back
to a tiny built-in lexicon so the pipeline still works.

Framing (leader / also-ran / cautionary) is a rule-based read over the sentences
that mention the brand, combined with the sentiment label.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from backend.config import settings

logger = logging.getLogger(__name__)

_pipe = None
_pipe_loaded = False

LEADER_CUES = (
    "best", "top", "leading", "#1", "number one", "most popular", "recommended",
    "go-to", "industry standard", "gold standard", "market leader", "top pick",
    "the best", "strongest", "dominates", "winner", "standout",
)
CAUTION_CUES = (
    "avoid", "drawback", "downside", "limitation", "lacks", "not recommended",
    "weakness", "concern", "be careful", "falls short", "criticized", "however",
    "but it", "struggles", "outdated", "expensive", "complicated", "steep learning",
)

_POS_LEX = {
    "best", "great", "excellent", "powerful", "popular", "leading", "top",
    "recommended", "flexible", "loved", "intuitive", "strong", "reliable",
}
_NEG_LEX = {
    "worst", "bad", "poor", "weak", "limited", "lacks", "expensive", "complicated",
    "confusing", "outdated", "buggy", "avoid", "drawback", "downside",
}

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _get_pipe():
    global _pipe, _pipe_loaded
    if _pipe_loaded:
        return _pipe
    _pipe_loaded = True
    try:
        from transformers import pipeline  # type: ignore[import-not-found]

        _pipe = pipeline("sentiment-analysis", model=settings.sentiment_model, truncation=True)
        logger.info("loaded HF sentiment model: %s", settings.sentiment_model)
    except Exception:
        logger.warning(
            "transformers/torch unavailable — using lexicon sentiment fallback. "
            "Install with: pip install transformers torch"
        )
        _pipe = None
    return _pipe


@lru_cache(maxsize=1)
def _label_map() -> dict[str, str]:
    # cardiffnlp '-latest' returns negative/neutral/positive; older returns LABEL_0/1/2
    return {
        "negative": "negative", "neutral": "neutral", "positive": "positive",
        "label_0": "negative", "label_1": "neutral", "label_2": "positive",
    }


def _brand_sentences(brand: str, text: str) -> list[str]:
    b = brand.lower()
    return [s for s in _SENT_SPLIT.split(text) if b in s.lower()]


def _model_sentiment(text: str) -> str:
    pipe = _get_pipe()
    if pipe is not None:
        try:
            out = pipe(text[:512])
            label = (out[0]["label"] if out else "neutral").lower()
            return _label_map().get(label, "neutral")
        except Exception:
            logger.exception("HF sentiment inference failed; using lexicon")
    # lexicon fallback
    words = set(re.findall(r"[a-z']+", text.lower()))
    pos = len(words & _POS_LEX)
    neg = len(words & _NEG_LEX)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def analyze_framing(brand: str, response_text: str) -> dict[str, str | None]:
    """Return {sentiment, framing, rationale} for `brand` in `response_text`."""
    if not response_text or not response_text.strip():
        return {"sentiment": "not-mentioned", "framing": "not-mentioned", "rationale": ""}

    sents = _brand_sentences(brand, response_text)
    if not sents:
        return {"sentiment": "not-mentioned", "framing": "not-mentioned", "rationale": ""}

    ctx = " ".join(sents)
    sentiment = _model_sentiment(ctx)

    low = ctx.lower()
    leader = any(c in low for c in LEADER_CUES)
    caution = any(c in low for c in CAUTION_CUES)

    if sentiment == "negative" or caution:
        framing = "cautionary"
    elif leader or sentiment == "positive":
        framing = "leader"
    else:
        framing = "also-ran"

    rationale = sents[0].strip()[:200]
    return {"sentiment": sentiment, "framing": framing, "rationale": rationale}
