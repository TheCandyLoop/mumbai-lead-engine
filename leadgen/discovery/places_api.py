"""Google Places API (New) - Text Search. Official, permitted source (needs API key).

Note: phone/website/rating fields fall under the Enterprise SKU pricing tier.
"""
from __future__ import annotations
import time
import requests
from leadgen import config
from leadgen.models import Lead, now_iso

URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.nationalPhoneNumber", "places.internationalPhoneNumber",
    "places.websiteUri", "places.googleMapsUri", "places.rating",
    "places.userRatingCount", "places.primaryTypeDisplayName",
    "nextPageToken",
])


def discover(location: str, category: str, max_results: int = 60) -> list[Lead]:
    if not config.GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY not set. Use --source osm or set the key in .env")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {"textQuery": f"{category} in {location}", "pageSize": 20, "regionCode": "IN"}
    leads: list[Lead] = []
    while len(leads) < max_results:
        r = requests.post(URL, json=body, headers=headers, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for p in data.get("places", []):
            leads.append(_to_lead(p))
        token = data.get("nextPageToken")
        if not token:
            break
        body["pageToken"] = token
        time.sleep(1)  # be polite
    return leads[:max_results]


def _to_lead(p: dict) -> Lead:
    phone = p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or ""
    lead = Lead(
        company_name=(p.get("displayName") or {}).get("text", ""),
        category=(p.get("primaryTypeDisplayName") or {}).get("text", ""),
        address=p.get("formattedAddress", ""),
        phone=phone,
        website=p.get("websiteUri", ""),
        maps_url=p.get("googleMapsUri", ""),
        rating=p.get("rating"),
        review_count=p.get("userRatingCount"),
        source="google_places",
        source_id=p.get("id", ""),
        collected_at=now_iso(),
    )
    for f in ("company_name", "address", "phone", "website", "maps_url", "rating", "review_count"):
        if getattr(lead, f) not in ("", None):
            lead.provenance[f] = "verified"
    return lead
