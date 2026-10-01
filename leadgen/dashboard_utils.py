"""Pure data helpers for the dashboard (no Streamlit import -> unit-testable)."""
from __future__ import annotations
import json
from typing import Optional

import pandas as pd

QUAL_ORDER = ["Hot", "Warm", "Cold", "Incomplete", "Unscored"]
EXPORT_COLUMNS = ["lead_id", "company_name", "category", "address", "phone", "email", "website", "maps_url",
                  "rating", "review_count", "social_links", "services", "lead_score", "qualification",
                  "qualification_reason", "source", "collected_at", "is_complete"]
PROV_LABEL = {"verified": "Verified (source / own website)", "ai_inferred": "AI-inferred",
              "rule_based": "Rule-based (computed from verified fields)"}


def _loads(v, default):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if isinstance(v, str) and v.strip() else default
    except json.JSONDecodeError:
        return default


def load_df(path_or_buffer) -> pd.DataFrame:
    df = pd.read_csv(path_or_buffer)
    for c in ("company_name", "category", "address", "phone", "email", "website", "maps_url",
              "qualification", "qualification_reason", "source", "collected_at", "lead_id"):
        df[c] = df[c].fillna("").astype(str) if c in df else ""
    for c in ("rating", "review_count", "lead_score"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else float("nan")
    df["is_complete"] = (df["is_complete"].astype(str).str.lower() == "true") if "is_complete" in df else True
    for c, d in (("social_links", {}), ("services", []), ("provenance", {})):
        df[c] = df[c].apply(lambda v, d=d: _loads(v, d)) if c in df else [d] * len(df)
    df["qualification"] = df["qualification"].replace("", "Unscored")
    df["social_str"] = df["social_links"].apply(lambda d: ", ".join(d))
    df["services_str"] = df["services"].apply(", ".join)
    return df


def source_tokens(df: pd.DataFrame) -> list[str]:
    return sorted({t for s in df["source"] for t in s.split("+") if t})


def apply_filters(df: pd.DataFrame, quals: Optional[list] = None, score_range: tuple = (0, 100),
                  sources: Optional[list] = None, only_complete: bool = False, need_phone: bool = False,
                  need_email: bool = False, need_website: bool = False, query: str = "") -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if quals is not None:
        m &= df["qualification"].isin(quals)
    lo, hi = score_range
    m &= df["lead_score"].between(lo, hi) | (df["lead_score"].isna() & (lo == 0))
    if sources:
        m &= df["source"].apply(lambda s: bool(set(s.split("+")) & set(sources)))
    if only_complete:
        m &= df["is_complete"]
    if need_phone:
        m &= df["phone"] != ""
    if need_email:
        m &= df["email"] != ""
    if need_website:
        m &= df["website"] != ""
    q = query.strip().lower()
    if q:
        hay = (df["company_name"] + " " + df["address"] + " " + df["category"] + " " + df["services_str"]).str.lower()
        m &= hay.str.contains(q, regex=False)
    out = df[m].copy()
    return out.sort_values("lead_score", ascending=False, na_position="last")


def summary(df: pd.DataFrame) -> dict:
    s = {"total": len(df), "avg_score": round(float(df["lead_score"].mean()), 1) if df["lead_score"].notna().any() else None,
         "complete": int(df["is_complete"].sum()), "with_email": int((df["email"] != "").sum()),
         "with_phone": int((df["phone"] != "").sum())}
    for q in QUAL_ORDER:
        s[q] = int((df["qualification"] == q).sum())
    return s


def export_csv(df: pd.DataFrame) -> bytes:
    out = df.copy()
    out["social_links"] = out["social_links"].apply(lambda d: "; ".join(f"{k}: {v}" for k, v in d.items()))
    out["services"] = out["services_str"]
    cols = [c for c in EXPORT_COLUMNS if c in out]
    return out[cols].to_csv(index=False).encode("utf-8")


def provenance_rows(row: pd.Series) -> list[dict]:
    """Field | Value | Provenance for the lead detail panel."""
    prov = row["provenance"]
    fields = [("company_name", "Company"), ("phone", "Phone"), ("email", "Email"), ("website", "Website"),
              ("address", "Address"), ("maps_url", "Maps URL"), ("rating", "Rating"),
              ("review_count", "Review count"), ("services", "Services")]
    rows = []
    for key, label in fields:
        val = row["services_str"] if key == "services" else row[key]
        if val in ("", None) or (isinstance(val, float) and pd.isna(val)):
            rows.append({"Field": label, "Value": "-", "Provenance": "Not found"})
        else:
            rows.append({"Field": label, "Value": str(val),
                         "Provenance": PROV_LABEL.get(prov.get(key, ""), "Source record (untagged)")})
    for net, url in row["social_links"].items():
        rows.append({"Field": f"Social: {net}", "Value": url,
                     "Provenance": PROV_LABEL.get(prov.get(f"social_{net}", ""), "Source record (untagged)")})
    for key, label in (("lead_score", "Lead score"), ("qualification_reason", "Qualification reason")):
        v = row[key]
        if not (isinstance(v, float) and pd.isna(v)) and v != "":
            rows.append({"Field": label, "Value": str(int(v)) if key == "lead_score" else v,
                         "Provenance": PROV_LABEL.get(prov.get(key, ""), "-")})
    return rows
