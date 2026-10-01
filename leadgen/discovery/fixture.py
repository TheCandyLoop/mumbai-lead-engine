"""Offline loader for the synthetic sample (used for tests/demo without network)."""
from __future__ import annotations
import json
from pathlib import Path
from leadgen.models import Lead, now_iso

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "sample_raw.json"


def discover(location: str = "Mumbai", category: str = "coworking space", max_results: int = 500) -> list[Lead]:
    rows = json.loads(FIXTURE.read_text())
    out = []
    for r in rows[:max_results]:
        l = Lead.from_dict(r)
        l.source = "fixture"
        l.collected_at = now_iso()
        for f in ("company_name", "address", "phone", "email", "website"):
            if getattr(l, f):
                l.provenance[f] = "verified"
        out.append(l)
    return out
