"""Adapter tests using realistic payload shapes + mocked HTTP (no network)."""
import pytest
from leadgen.discovery import osm, places_api
from leadgen.cleaning import clean_and_dedupe

PLACE = {
    "id": "ChIJabc", "displayName": {"text": "Test Cowork Bandra", "languageCode": "en"},
    "formattedAddress": "Linking Rd, Bandra West, Mumbai, Maharashtra 400050, India",
    "internationalPhoneNumber": "+91 22 4000 1111", "websiteUri": "https://testcowork.in/",
    "googleMapsUri": "https://maps.google.com/?cid=1", "rating": 4.5, "userRatingCount": 120,
    "primaryTypeDisplayName": {"text": "Coworking space"},
}


class Resp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


def test_places_to_lead():
    l = places_api._to_lead(PLACE)
    assert l.company_name == "Test Cowork Bandra" and l.review_count == 120 and l.source == "google_places"
    assert l.provenance["phone"] == "verified" and l.source_id == "ChIJabc"
    assert clean_and_dedupe([l])[0][0].phone == "+912240001111"


def test_places_requires_key(monkeypatch):
    monkeypatch.setattr(places_api.config, "GOOGLE_PLACES_API_KEY", "")
    with pytest.raises(RuntimeError):
        places_api.discover("Mumbai", "coworking space")


def test_places_pagination_and_limit(monkeypatch):
    monkeypatch.setattr(places_api.config, "GOOGLE_PLACES_API_KEY", "k")
    monkeypatch.setattr(places_api.time, "sleep", lambda s: None)
    pages = [{"places": [PLACE] * 20, "nextPageToken": "t2"}, {"places": [PLACE] * 20}]
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((json.copy(), headers))
        return Resp(pages[len(calls) - 1])
    monkeypatch.setattr(places_api.requests, "post", fake_post)
    out = places_api.discover("Mumbai", "coworking space", max_results=30)
    assert len(out) == 30 and len(calls) == 2
    assert calls[0][0]["textQuery"] == "coworking space in Mumbai"
    assert calls[1][0]["pageToken"] == "t2"
    assert "places.websiteUri" in calls[0][1]["X-Goog-FieldMask"]


def test_osm_to_lead_and_unnamed_skipped():
    el = {"type": "node", "id": 42, "tags": {
        "name": "OSM Cowork", "office": "coworking", "addr:street": "SV Road", "addr:suburb": "Andheri",
        "addr:city": "Mumbai", "addr:postcode": "400058", "contact:phone": "+91 22 2600 1234; +91 98200 00000",
        "contact:website": "https://osmcowork.in", "contact:linkedin": "https://linkedin.com/company/osmcowork"}}
    l = osm._to_lead(el, "coworking space")
    assert l.maps_url.endswith("/node/42") and l.phone.startswith("+91 22 2600")  # first of multiple
    assert l.social_links["linkedin"] and l.address.endswith("400058")
    assert osm._to_lead({"type": "node", "id": 1, "tags": {"office": "coworking"}}, "x") is None


def test_osm_discover_builds_query_and_parses(monkeypatch):
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)
    seen = {}
    monkeypatch.setattr(osm.requests, "get", lambda *a, **k: Resp([{"boundingbox": ["18.89", "19.27", "72.77", "72.99"]}]))

    def fake_post(url, data=None, headers=None, timeout=None):
        seen["q"] = data["data"]
        return Resp({"elements": [{"type": "way", "id": 7, "center": {"lat": 19, "lon": 72},
                                   "tags": {"name": "Way Cowork", "email": "a@b.in"}}]})
    monkeypatch.setattr(osm.requests, "post", fake_post)
    out = osm.discover("Mumbai", "coworking space")
    assert len(out) == 1 and out[0].email == "a@b.in"
    assert '"office"="coworking"' in seen["q"] and "18.89,72.77,19.27,72.99" in seen["q"]


def test_osm_unknown_category():
    with pytest.raises(ValueError):
        osm._tags_for("pizza shop")
