from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from backend.utils.helpers import brand_root_from_domain


_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|gmbh|labs?|technologies|technology|software|app|ai|hq|corp|co)\b\.?",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s&]+")
_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SUFFIX_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


@dataclass
class NormalizedBrand:
    canonical: str            # display form
    key: str                  # normalized key
    aliases: set[str] = field(default_factory=set)
    domains: set[str] = field(default_factory=set)


class EntityNormalizer:
    """Groups raw entity strings into canonical brands using rapidfuzz + domain hints.

    The known map seeds the grouping with explicit aliases (e.g. the target brand + competitors).
    Everything else is bucketed by fuzzy similarity.
    """

    SIM_THRESHOLD = 88

    def __init__(self, known: dict[str, list[str]] | None = None):
        self.brands: dict[str, NormalizedBrand] = {}
        if known:
            for canonical, aliases in known.items():
                self.add_known(canonical, aliases)

    def add_known(self, canonical: str, aliases: list[str]) -> None:
        key = normalize_name(canonical)
        if not key:
            return
        brand = self.brands.get(key) or NormalizedBrand(canonical=canonical, key=key)
        brand.aliases.add(key)
        for a in aliases:
            ak = normalize_name(a)
            if ak:
                brand.aliases.add(ak)
        # also seed domain root as alias
        root = brand_root_from_domain(canonical)
        if root:
            brand.aliases.add(root)
        self.brands[key] = brand

    def add_domain(self, canonical_key: str, domain: str) -> None:
        b = self.brands.get(canonical_key)
        if b:
            b.domains.add(domain.lower())

    def resolve(self, raw_name: str) -> str | None:
        """Return canonical key for a raw entity string, creating a new group if needed."""
        key = normalize_name(raw_name)
        if not key:
            return None
        # direct alias hit
        for ckey, brand in self.brands.items():
            if key in brand.aliases:
                return ckey
        # fuzzy match against existing aliases
        all_aliases = [(alias, ckey) for ckey, b in self.brands.items() for alias in b.aliases]
        if all_aliases:
            choices = [a for a, _ in all_aliases]
            match = process.extractOne(key, choices, scorer=fuzz.token_set_ratio)
            if match and match[1] >= self.SIM_THRESHOLD:
                matched_alias = match[0]
                for alias, ckey in all_aliases:
                    if alias == matched_alias:
                        self.brands[ckey].aliases.add(key)
                        return ckey
        # new brand
        self.brands[key] = NormalizedBrand(canonical=raw_name.strip(), key=key, aliases={key})
        return key

    def canonical_for(self, key: str) -> str:
        b = self.brands.get(key)
        return b.canonical if b else key

    def lookup_by_domain(self, domain: str) -> str | None:
        domain = (domain or "").lower()
        if not domain:
            return None
        root = brand_root_from_domain(domain)
        for ckey, b in self.brands.items():
            if domain in b.domains:
                return ckey
            if root and any(brand_root_from_domain(d) == root for d in b.domains):
                return ckey
            if root and (root in b.aliases or root == ckey):
                return ckey
        return None
