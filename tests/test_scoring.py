import json
from leadgen.models import Lead
from leadgen.scoring import (baseline, label_for, parse_llm_json, score_lead, score_leads,
                             INCOMPLETE_CAP, LLM_MAX_SHIFT, WEIGHTS)


def strong():
    return Lead(company_name="HiveSpace", phone="+919820011223", email="a@b.in", website="https://b.in",
                address="Andheri East 400069", rating=4.8, review_count=540,
                services=["hot desk", "meeting room", "day pass", "parking", "24/7 access"],
                social_links={"linkedin": "x", "instagram": "y", "facebook": "z"}, is_complete=True)


def weak():
    return Lead(company_name="Ghost", address="Somewhere, Mumbai", is_complete=False)


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_strong_is_hot_with_evidence_reason():
    b = baseline(strong())
    assert b["score"] == 100 and b["label"] == "Hot"
    assert "4.8 rating from 540 reviews" in b["reason"] and "phone+email+website" in b["reason"]


def test_incomplete_capped_and_labelled():
    l = strong(); l.phone = l.email = ""; l.is_complete = False
    b = baseline(l)
    assert b["score"] <= INCOMPLETE_CAP and b["label"] == "Incomplete"
    assert "Incomplete lead" in b["reason"]
    assert baseline(weak())["label"] == "Incomplete"


def test_label_thresholds():
    assert [label_for(s, True) for s in (70, 69, 40, 39)] == ["Hot", "Warm", "Warm", "Cold"]


def test_rule_only_scoring_sets_provenance():
    l = score_lead(strong())
    assert l.lead_score == 100 and l.qualification == "Hot"
    assert l.provenance["lead_score"] == "rule_based"


def test_parse_llm_json():
    assert parse_llm_json('```json\n{"score": 71.6, "reason": "good"}\n```') == {"score": 72, "reason": "good"}
    for bad in ("", "no json", '{"score": 150, "reason": "x"}', '{"score": "a", "reason": "x"}', '{"score": 5}'):
        assert parse_llm_json(bad) is None


def mk_llm(score, reason="Strong reviews and full contact info"):
    return lambda payload: json.dumps({"score": score, "reason": reason})


def test_llm_shift_is_clamped_and_label_derived_from_score():
    l = Lead(company_name="Mid", phone="+912212345678", website="https://m.in", rating=4.0, review_count=40,
             is_complete=True)
    base = baseline(l)["score"]
    score_lead(l, mk_llm(100))                       # LLM tries to inflate
    assert l.lead_score == min(100, base + LLM_MAX_SHIFT)
    assert l.provenance["lead_score"] == "ai_inferred" and l.provenance["qualification_reason"] == "ai_inferred"
    assert l.qualification_reason.startswith(l.qualification)


def test_llm_cannot_lift_incomplete_above_cap():
    l = weak()
    score_lead(l, mk_llm(95))
    assert l.lead_score <= INCOMPLETE_CAP and l.qualification == "Incomplete"


def test_llm_failures_fall_back_to_baseline():
    def boom(_): raise RuntimeError("rate limited")
    for llm in (boom, lambda p: "garbage"):
        l = score_lead(strong(), llm)
        assert l.lead_score == 100 and l.provenance["lead_score"] == "rule_based"


def test_payload_has_no_raw_contact_values():
    seen = {}
    def spy(payload): seen.update(payload); return '{"score": 90, "reason": "ok"}'
    score_lead(strong(), spy)
    blob = json.dumps(seen)
    assert "+919820011223" not in blob and "a@b.in" not in blob   # only has_phone / has_email flags


def test_score_leads_rules_only_without_key(monkeypatch):
    from leadgen import config
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    out = score_leads([strong(), weak()])
    assert [l.qualification for l in out] == ["Hot", "Incomplete"]


def test_social_page_is_not_a_website():
    a = Lead(company_name="A", phone="+912212345678", website="https://facebook.com/a", is_complete=True)
    b = Lead(company_name="B", phone="+912212345678", website="https://b.in", is_complete=True)
    assert baseline(b)["score"] - baseline(a)["score"] == WEIGHTS["website"]
