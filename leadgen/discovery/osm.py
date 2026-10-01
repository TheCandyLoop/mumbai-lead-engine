"""OpenStreetMap discovery (Nominatim geocode + Overpass). Free, open-data, permitted.

Respect usage policies: identify via User-Agent, low request rate.
"""
from __future__ import annotations
import time
import requests
from leadgen import config
from leadgen.models import Lead, now_iso

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"

# category keyword -> list of OSM tag filters
CATEGORY_TAGS = {
    "cowork": ['["office"="coworking"]', '["amenity"="coworking_space"]', '["office"="coworking_space"]'],
}


def _tags_for(category: str) -> list[str]:
    c = category.lower()
    for key, tags in CATEGORY_TAGS.items():
        if key in c:
            return tags
    raise ValueError(f"No OSM tag mapping for category '{category}'. Add one in CATEGORY_TAGS.")


def _bbox(location: str) -> tuple[float, float, float, float]:
    r = requests.get(NOMINATIM, params={"q": location, "format": "json", "limit": 1},
                     headers={"User-Agent": config.USER_AGENT}, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    res = r.json()
    if not res:
        raise RuntimeError(f"Could not geocode '{location}'")
    s, n, w, e = map(float, res[0]["boundingbox"])  # south, north, west, east
    return s, w, n, e


def discover(location: str, category: str, max_results: int = 200) -> list[Lead]:
    s, w, n, e = _bbox(location)
    time.sleep(1)  # Nominatim policy: max 1 req/sec
    parts = "".join(f"nwr{t}({s},{w},{n},{e});" for t in _tags_for(category))
    query = f"[out:json][timeout:60];({parts});out center tags;"
    r = requests.post(OVERPASS, data={"data": query},
                      headers={"User-Agent": config.USER_AGENT}, timeout=90)
    r.raise_for_status()
    leads = [_to_lead(el, category) for el in r.json().get("elements", [])]
    return [l for l in leads if l][:max_results]


def _first(tags: dict, *keys: str) -> str:
    for k in keys:
        if tags.get(k):
            return tags[k].split(";")[0].strip()
    return ""


def _to_lead(el: dict, category: str) -> Lead | None:
    t = el.get("tags", {})
    name = t.get("name", "").strip()
    if not name:
        return None
    parts = [t.get("addr:housenumber", ""), t.get("addr:street", ""), t.get("addr:suburb", ""),
             t.get("addr:city", ""), t.get("addr:postcode", "")]
    address = ", ".join(p for p in parts if p)
    socials = {}
    for net in ("facebook", "instagram", "linkedin", "twitter"):
        v = _first(t, f"contact:{net}", net)
        if v:
            socials[net] = v
    lead = Lead(
        company_name=name,
        category=category,
        address=address,
        phone=_first(t, "contact:phone", "phone", "contact:mobile"),
        email=_first(t, "contact:email", "email"),
        website=_first(t, "contact:website", "website"),
        maps_url=f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
        social_links=socials,
        source="osm",
        source_id=f"{el['type']}/{el['id']}",
        collected_at=now_iso(),
    )
    for f in ("company_name", "address", "phone", "email", "website"):
        if getattr(lead, f):
            lead.provenance[f] = "verified"
    return lead
