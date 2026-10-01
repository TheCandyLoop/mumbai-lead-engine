from pathlib import Path
import pytest
from leadgen.dashboard_utils import apply_filters, export_csv, load_df, provenance_rows, summary, source_tokens
from leadgen.pipeline import run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def df(tmp_path_factory):
    p = tmp_path_factory.mktemp("d") / "leads.csv"
    run("fixture", "Mumbai", "coworking space", 100, str(p), enrich=False, score=True, use_llm=False)
    return load_df(p)


def test_load_and_summary(df):
    s = summary(df)
    assert s["total"] == 9 and s["Hot"] + s["Warm"] + s["Cold"] + s["Incomplete"] == 9
    assert s["Hot"] == 2 and s["Incomplete"] == 2


def test_filters(df):
    hot = apply_filters(df, quals=["Hot"])
    assert set(hot["qualification"]) == {"Hot"} and hot["lead_score"].is_monotonic_decreasing
    assert len(apply_filters(df, score_range=(50, 100))) == (df["lead_score"] >= 50).sum()
    assert apply_filters(df, only_complete=True)["is_complete"].all()
    assert (apply_filters(df, need_email=True)["email"] != "").all()
    assert len(apply_filters(df, query="powai")) == 1
    assert apply_filters(df, query="zzz").empty
    assert source_tokens(df) == ["fixture"] and len(apply_filters(df, sources=["fixture"])) == 9


def test_unscored_rows_survive_default_filter():
    import pandas as pd, io
    raw = "company_name,phone\nA Cowork,+912212345678\n"
    d = load_df(io.StringIO(raw))
    assert d.loc[0, "qualification"] == "Unscored"
    assert len(apply_filters(d, quals=["Unscored"])) == 1       # NaN score kept at (0,100)
    assert summary(d)["avg_score"] is None


def test_export_is_readable_csv(df):
    import io, pandas as pd
    out = pd.read_csv(io.BytesIO(export_csv(df)))
    assert list(out.columns)[:3] == ["lead_id", "company_name", "category"]
    assert "lead_score" in out and "{" not in "".join(out["social_links"].fillna("").astype(str))


def test_provenance_rows_label_sources(df):
    row = df[df["company_name"].str.contains("HiveSpace")].iloc[0]
    rows = {r["Field"]: r["Provenance"] for r in provenance_rows(row)}
    assert rows["Phone"].startswith("Verified")
    assert rows["Lead score"].startswith("Rule-based")
    assert rows["Lead score"] != "AI-inferred"


def test_streamlit_app_smoke():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=30).run()
    assert not at.exception, at.exception
    assert len(at.metric) == 6
    at.sidebar.multiselect[0].set_value(["Hot"]).run()      # filter interaction
    assert not at.exception
    assert at.metric[0].value.startswith("2 /")


def test_csv_integers_have_no_decimal_point(tmp_path):
    p = tmp_path / "x.csv"
    run("fixture", "Mumbai", "coworking space", 100, str(p), enrich=False, score=True, use_llm=False)
    txt = p.read_text()
    assert ",312," in txt and "312.0" not in txt and ",150," in txt
