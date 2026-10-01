from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from leadgen.models import Lead

COLUMNS = ["lead_id", "company_name", "category", "address", "phone", "email", "website", "maps_url",
           "rating", "review_count", "social_links", "services", "lead_score", "qualification",
           "qualification_reason", "source", "collected_at", "is_complete", "merged_from", "provenance"]


def save_leads(leads: list[Lead], csv_path: str) -> None:
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for l in leads:
        d = l.to_dict()
        for k in ("social_links", "services", "provenance"):
            d[k] = json.dumps(d[k], ensure_ascii=False)
        rows.append(d)
    df = pd.DataFrame(rows, columns=COLUMNS)
    for c in ("review_count", "lead_score"):   # keep integers as integers even with blanks
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    df.to_csv(csv_path, index=False)


def load_leads(csv_path: str) -> list[Lead]:
    df = pd.read_csv(csv_path).fillna("")
    out = []
    for r in df.to_dict("records"):
        for k in ("social_links", "services", "provenance"):
            r[k] = json.loads(r[k]) if r.get(k) else ({} if k != "services" else [])
        for k in ("rating", "review_count", "lead_score"):
            r[k] = None if r.get(k) == "" else r[k]
        if r.get("review_count") is not None: r["review_count"] = int(r["review_count"])
        if r.get("lead_score") is not None: r["lead_score"] = int(r["lead_score"])
        r["is_complete"] = str(r.get("is_complete")).lower() == "true"
        out.append(Lead.from_dict(r))
    return out
