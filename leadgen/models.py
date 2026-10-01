"""Lead schema shared by every pipeline stage."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Lead:
    company_name: str = ""
    category: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    maps_url: str = ""
    rating: Optional[float] = None
    review_count: Optional[int] = None
    social_links: dict = field(default_factory=dict)   # {"linkedin": url, ...}
    services: list = field(default_factory=list)       # e.g. ["hot desk", "meeting room"]
    lead_score: Optional[int] = None
    qualification: str = ""                            # Hot / Warm / Cold / Incomplete
    qualification_reason: str = ""
    source: str = ""                                   # google_places | osm | fixture
    source_id: str = ""                                # provider's id (place_id / osm id)
    collected_at: str = field(default_factory=now_iso)
    lead_id: str = ""
    # field -> "verified" (from source / page) or "ai_inferred"
    provenance: dict = field(default_factory=dict)
    is_complete: bool = False                          # name AND (phone OR email)
    merged_from: int = 1                               # duplicates collapsed into this row

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Lead":
        known = {k: v for k, v in d.items() if k in Lead.__dataclass_fields__}
        return Lead(**known)
