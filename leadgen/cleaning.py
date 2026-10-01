"""Normalization + deduplication.

Dedup strategy (union-find over match rules, then merge each cluster):
  1. same normalized phone (E.164)
  2. same normalized email   (only if pincodes don't conflict - multi-branch brands)
  3. same website domain     (same guard; ignores social / aggregator domains)
  4. fuzzy name (token_sort_ratio >= 88) AND (fuzzy address >= 60 OR same pincode)
Within a cluster the richest record is the base and gaps are filled from the others.
"""
from __future__ import annotations
import hashlib
import re
from urllib.parse import urlparse

import phonenumbers
from rapidfuzz import fuzz

from leadgen import config
from leadgen.models import Lead

SOCIAL_DOMAINS = {"facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
                  "youtube.com", "justdial.com", "wa.me", "g.page", "goo.gl", "business.site"}
NAME_NOISE = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|co|the|mumbai|india)\b\.?", re.I)
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
PIN_RE = re.compile(r"\b(4\d{5})\b")


# ---------- field normalizers ----------
def norm_phone(raw: str) -> str:
    """Return E.164 (e.g. +912212345678) or '' if invalid."""
    if not raw:
        return ""
    raw = re.split(r"[;,/]|\bor\b", raw)[0].strip()
    try:
        num = phonenumbers.parse(raw, config.DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return ""
    if not phonenumbers.is_possible_number(num):
        return ""
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def norm_email(raw: str) -> str:
    raw = (raw or "").strip().lower().removeprefix("mailto:")
    return raw if EMAIL_RE.match(raw) else ""


def norm_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    host = p.netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    path = p.path.rstrip("/")
    return f"{p.scheme.lower()}://{host}{path}"


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.") if url else ""


def norm_name(raw: str) -> str:
    """Display-clean name (collapse whitespace, strip junk)."""
    return re.sub(r"\s+", " ", (raw or "")).strip(" -|,.")


def name_key(raw: str) -> str:
    s = NAME_NOISE.sub(" ", (raw or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_address(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "")).strip(" ,")


def pincode(addr: str) -> str:
    m = PIN_RE.search(addr or "")
    return m.group(1) if m else ""


# ---------- cleaning ----------
def clean_lead(l: Lead) -> Lead:
    l.company_name = norm_name(l.company_name)
    l.address = norm_address(l.address)
    l.phone = norm_phone(l.phone)
    l.email = norm_email(l.email)
    l.website = norm_url(l.website)
    l.category = (l.category or "").strip().lower()
    l.is_complete = bool(l.company_name and (l.phone or l.email))
    # drop provenance for fields that became empty after validation
    for f in ("phone", "email", "website", "address"):
        if not getattr(l, f):
            l.provenance.pop(f, None)
    return l


# ---------- dedup ----------
class _UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def _same_business(a: Lead, b: Lead) -> bool:
    pa, pb = pincode(a.address), pincode(b.address)
    different_area = bool(pa and pb and pa != pb)  # multi-branch brands share domain/email

    if a.phone and a.phone == b.phone:
        return True
    if not different_area:
        if a.email and a.email == b.email:
            return True
        da, db = domain(a.website), domain(b.website)
        if da and da == db and da not in SOCIAL_DOMAINS:
            return True
    if fuzz.token_sort_ratio(name_key(a.company_name), name_key(b.company_name)) >= 88:
        if (pa and pa == pb) or fuzz.token_set_ratio(a.address, b.address) >= 60 or not (a.address and b.address):
            return True
    return False


def _richness(l: Lead) -> int:
    return sum(bool(getattr(l, f)) for f in
               ("phone", "email", "website", "address", "maps_url", "rating", "review_count")) + len(l.social_links)


def _merge(cluster: list[Lead]) -> Lead:
    cluster = sorted(cluster, key=_richness, reverse=True)
    base = cluster[0]
    for other in cluster[1:]:
        for f in ("phone", "email", "website", "address", "maps_url", "category"):
            if not getattr(base, f) and getattr(other, f):
                setattr(base, f, getattr(other, f))
                if f in other.provenance:
                    base.provenance[f] = other.provenance[f]
        if base.rating is None and other.rating is not None:
            base.rating, base.review_count = other.rating, other.review_count
        for k, v in other.social_links.items():
            base.social_links.setdefault(k, v)
        if other.source not in base.source.split("+"):
            base.source = f"{base.source}+{other.source}"
    base.merged_from = len(cluster)
    base.is_complete = bool(base.company_name and (base.phone or base.email))
    return base


def deduplicate(leads: list[Lead]) -> list[Lead]:
    n = len(leads)
    uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if uf.find(i) != uf.find(j) and _same_business(leads[i], leads[j]):
                uf.union(i, j)
    clusters: dict[int, list[Lead]] = {}
    for i, l in enumerate(leads):
        clusters.setdefault(uf.find(i), []).append(l)
    return [_merge(c) for c in clusters.values()]


def assign_ids(leads: list[Lead]) -> list[Lead]:
    for l in leads:
        key = l.phone or domain(l.website) or f"{name_key(l.company_name)}|{pincode(l.address)}"
        l.lead_id = "L-" + hashlib.sha1(key.encode()).hexdigest()[:10]
    return leads


def clean_and_dedupe(leads: list[Lead]) -> tuple[list[Lead], dict]:
    cleaned = [clean_lead(l) for l in leads if (l.company_name or "").strip()]
    deduped = assign_ids(deduplicate(cleaned))
    stats = {
        "raw": len(leads),
        "dropped_no_name": len(leads) - len(cleaned),
        "after_dedupe": len(deduped),
        "duplicates_removed": len(cleaned) - len(deduped),
        "complete": sum(l.is_complete for l in deduped),
        "incomplete": sum(not l.is_complete for l in deduped),
    }
    return deduped, stats
