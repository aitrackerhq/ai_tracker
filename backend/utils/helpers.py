import asyncio
import random
import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

import tldextract


def new_run_id() -> str:
    return f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def domain_from_url(url: str) -> str:
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
        netloc = urlparse(url).netloc
        return netloc.lower()
    except Exception:
        return ""


def brand_root_from_domain(domain: str) -> str:
    ext = tldextract.extract(domain)
    return (ext.domain or "").lower()


WHITESPACE_RE = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


async def human_pause(low: float = 0.04, high: float = 0.14) -> None:
    await asyncio.sleep(random.uniform(low, high))
