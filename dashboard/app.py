"""Streamlit dashboard.  Run:  streamlit run dashboard/app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from leadgen.dashboard_utils import (QUAL_ORDER, apply_filters, export_csv, load_df, provenance_rows,
                                     source_tokens, summary)

st.set_page_config(page_title="Mumbai Coworking Leads", page_icon=":office:", layout="wide")
CANDIDATES = [ROOT / "data" / n for n in ("leads.csv", "sample_leads.csv")]


@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float) -> pd.DataFrame:  # mtime busts cache when file changes
    return load_df(path)


# ---------------------------------------------------------------- data selection
st.sidebar.header("Data")
default = next((str(p) for p in CANDIDATES if p.exists()), "")
upload = st.sidebar.file_uploader("Upload a leads CSV", type="csv")
path = st.sidebar.text_input("...or CSV path", default)

df = None
try:
    if upload is not None:
        df = load_df(upload)
    elif path and Path(path).exists():
        df = _load(path, Path(path).stat().st_mtime)
except Exception as e:
    st.error(f"Could not read that CSV: {e}")

st.title("Mumbai Coworking Space Leads")
if df is None or df.empty:
    st.info("No data yet. Generate leads with `python -m leadgen.pipeline --source osm --enrich --score` "
            "or upload a CSV in the sidebar.")
    st.stop()

# ---------------------------------------------------------------- filters
st.sidebar.header("Filters")
present = [q for q in QUAL_ORDER if q in set(df["qualification"])]
quals = st.sidebar.multiselect("Qualification", present, default=present)
score_range = st.sidebar.slider("Lead score", 0, 100, (0, 100))
sources = st.sidebar.multiselect("Source", source_tokens(df))
only_complete = st.sidebar.checkbox("Complete leads only (name + phone/email)")
c1, c2, c3 = st.sidebar.columns(3)
need_phone, need_email, need_web = c1.checkbox("Phone"), c2.checkbox("Email"), c3.checkbox("Website")
query = st.sidebar.text_input("Search name / address / service")

view = apply_filters(df, quals, score_range, sources, only_complete, need_phone, need_email, need_web, query)

# ---------------------------------------------------------------- summary
s = summary(view)
cols = st.columns(6)
cols[0].metric("Leads shown", f"{s['total']} / {len(df)}")
cols[1].metric("Hot", s["Hot"])
cols[2].metric("Warm", s["Warm"])
cols[3].metric("Cold", s["Cold"])
cols[4].metric("Incomplete", s["Incomplete"])
cols[5].metric("Avg score", s["avg_score"] if s["avg_score"] is not None else "-")
st.caption(f"{s['with_phone']} with phone | {s['with_email']} with email | {s['complete']} complete")

if view.empty:
    st.warning("No leads match these filters.")
    st.stop()

left, right = st.columns([3, 1])
with right:
    st.caption("Leads by qualification")
    st.bar_chart(view["qualification"].value_counts().reindex(QUAL_ORDER).dropna())
    st.download_button("Download filtered CSV", export_csv(view), "mumbai_coworking_leads.csv", "text/csv",
                       use_container_width=True)

# ---------------------------------------------------------------- table
with left:
    show = view[["company_name", "qualification", "lead_score", "phone", "email", "website", "rating",
                 "review_count", "address", "services_str", "social_str", "source", "qualification_reason"]]
    st.dataframe(
        show, use_container_width=True, hide_index=True, height=420,
        column_config={
            "lead_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "website": st.column_config.LinkColumn("Website"),
            "rating": st.column_config.NumberColumn("Rating", format="%.1f"),
            "review_count": st.column_config.NumberColumn("Reviews", format="%d"),
            "services_str": "Services", "social_str": "Socials",
            "company_name": "Company", "qualification": "Qualification",
            "qualification_reason": st.column_config.TextColumn("Reason", width="large"),
        },
    )

# ---------------------------------------------------------------- detail
st.subheader("Lead detail: verified vs AI-inferred")
ids = view["lead_id"].tolist()
names = dict(zip(view["lead_id"], view["company_name"]))
pick = st.selectbox("Select a lead", ids, format_func=lambda i: f"{names[i]} ({i})")
row = view[view["lead_id"] == pick].iloc[0]
st.markdown(f"**{row['company_name']}** | {row['qualification']} | score "
            f"{'' if pd.isna(row['lead_score']) else int(row['lead_score'])}")
st.dataframe(pd.DataFrame(provenance_rows(row)), hide_index=True, use_container_width=True)
if row["maps_url"]:
    st.link_button("Open map reference", row["maps_url"])
