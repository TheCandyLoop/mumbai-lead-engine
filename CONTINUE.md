# CONTINUE.md  (handoff file - read this first in a new chat)

## >>> ALL 5 STAGES BUILT. Remaining = USER-SIDE steps (cannot be done in the sandbox: no internet) <<<
1. `pip install -r requirements.txt`, `cp .env.example .env`, add GOOGLE_PLACES_API_KEY and/or ANTHROPIC_API_KEY.
2. Real run: `python -m leadgen.pipeline --source osm --location "Mumbai" --category "coworking space" --enrich --score --out data/leads.csv`
   (and/or `--source places`; for more coverage run per-neighbourhood queries). Fix any live-data surprises
   (parser tweaks, OSM tag coverage). First live run of Places/Overpass/real websites/Claude scoring is UNTESTED.
3. Replace data/sample_leads.csv with the real output (or commit data/leads.csv); update the README "Limitations" first bullet.
4. `streamlit run dashboard/app.py`, take 1-2 screenshots for the submission (deploy free on Streamlit Community Cloud for a demo link).
5. Push to GitHub (or zip), include README + sample dataset + dashboard link. Mention the synthetic fixture is for offline demo only.

## Project
Mumbai coworking lead discovery & qualification (Yanisa AI Engineer Intern assignment).
Pipeline: discover -> clean/dedupe -> enrich -> AI score -> Streamlit dashboard + CSV + README.
Mandatory lead rule: company_name AND (phone OR email); otherwise `is_complete=False`.
Constraint: no CAPTCHA/auth bypass, no scraping Google Maps pages. Use Places API (New) or OSM only.

## STATUS
- [x] Stage 1: scaffold, models, discovery (places_api.py, osm.py, fixture.py), cleaning + dedup, pipeline CLI, 6 passing tests
- [x] Stage 2: enrichment (leadgen/enrichment.py) DONE - 12 tests passing
- [x] Stage 3: scoring (leadgen/scoring.py) DONE - 24 tests passing
- [x] Stage 4: dashboard (dashboard/app.py + leadgen/dashboard_utils.py) DONE - 30 tests passing
- [x] Stage 5: README.md, .gitignore, tests/test_discovery.py (adapter tests), regenerated data/sample_leads.csv. 37 tests passing.

## Files that exist
leadgen/{config,models,cleaning,io_utils,pipeline}.py, leadgen/discovery/{places_api,osm,fixture}.py,
tests/test_cleaning.py, data/sample_raw.json (SYNTHETIC fictional businesses, *.example domains),
data/sample_leads.csv, requirements.txt, .env.example

## Stage 2 facts (done)
- enrichment.py: pure `parse_html(html, base_url)`; `Fetcher` (robots.txt, 403 on robots => don't crawl, 1.5s delay,
  15s timeout, 1.5MB cap, HTML only); max 3 pages/site (home + contact + about); `enrich_leads(leads, fetcher=None)`.
- Never overwrites existing values; fills email/phone/social_links/services; provenance="verified" for everything
  scraped (keys: email, phone, services, social_<network>). Skips social/aggregator and reserved TLDs (.example etc).
- Tests: tests/test_enrichment.py (parser, fake fetcher), tests/test_fetcher.py (local HTTP server).
- Stage 3 should tag LLM-produced content as provenance="ai_inferred" (e.g. qualification_reason, any inferred fields).
- Lead has NO `description` field; if scoring wants site text, add a field to models.py + io_utils.COLUMNS.

## Stage 3 facts (done)
- scoring.py: `score_leads(leads, use_llm=True, llm=None)`; CLI flags `--score` and `--no-llm`.
- Rule baseline weights (sum 100): contact 30 (phone15+email15), website 10 (social-page URL doesn't count), rating 15,
  reviews 15, services 15 (3 each), social 10, address 5. Incomplete leads capped at 39.
- LLM layer (claude-sonnet-4-6, temp 0): sees only structured fields + flags (no raw phone/email, no web text);
  may shift score at most +/-15 from baseline; JSON validated; ANY failure -> baseline. Label always derived from score.
- Thresholds: Hot>=70, Warm 40-69, Cold<40, Incomplete if not is_complete.
- provenance["lead_score"] and ["qualification_reason"] = "rule_based" | "ai_inferred".
- Fixture result (rules only): Hot 2, Warm 3, Cold 2, Incomplete 2. data/leads_stage3.csv is a sample output.
- LLM path is tested with fake callables only (no API key in sandbox) -> first real-key run on user's machine is untested.

## Stage 4 facts (done)
- dashboard/app.py = thin UI; all logic in leadgen/dashboard_utils.py (load_df, apply_filters, summary, export_csv,
  provenance_rows) so it is unit-tested; tests/test_dashboard.py includes a headless AppTest smoke test.
- Data source order: sidebar upload > path box (default data/leads.csv, falls back to data/sample_leads.csv).
- Features: qualification/score/source/completeness/phone/email/website/search filters, 6 metric cards, bar chart,
  sortable table w/ progress+link columns, filtered CSV download, lead detail with verified / AI-inferred / rule-based labels.
- data/sample_leads.csv = SYNTHETIC fixture output (rules-only scoring). Regenerate in Stage 5.
- Server boot verified (health endpoint ok); no visual screenshot was taken in sandbox.

## Key design facts (don't re-derive)
- `Lead` dataclass in models.py; `provenance` dict maps field -> "verified" | "ai_inferred".
- pipeline.py already has hooks: `--enrich` calls `leadgen.enrichment.enrich_leads(leads)->leads`,
  `--score` calls `leadgen.scoring.score_leads(leads)->leads`. Just create those modules.
- io_utils.save_leads/load_leads handle CSV (dict/list columns stored as JSON strings).
- Dedup: union-find; rules = same phone | same email/domain (blocked if pincodes differ) | fuzzy name>=88 + address/pincode.
  Known limitation: shared central phone number across branches would merge them.
- Run in Places mode needs GOOGLE_PLACES_API_KEY in .env; OSM mode is free. The sandbox
  had no internet to Overpass/Google, so real-data runs must be done on the user's machine.

## Stage 2 spec (enrichment.py)
- For each lead with a website (skip social/aggregator domains): check robots.txt (urllib.robotparser),
  User-Agent from config, 1-2s delay, timeout, max 3 pages (home, /contact, /about).
- Extract with BeautifulSoup: emails (mailto + regex, skip image/example junk), phones (tel: links),
  social links (linkedin/facebook/instagram/twitter/youtube), services via keyword match
  (hot desk, dedicated desk, private cabin/office, meeting room, day pass, virtual office, event space, 24/7, cafeteria).
- Mark scraped fields provenance="verified"; keyword-guessed services from page text = "verified" if literal match,
  anything LLM-derived = "ai_inferred". Update is_complete after enrichment.
- Must be offline-testable: split into pure `parse_html(html, base_url)` + network `fetch()`; write tests with sample HTML.
- Never raise on a failing site; log and continue.

## Stage 3 spec (scoring.py)
- score_leads(leads): rule-based baseline (0-100) ALWAYS computed: completeness (30), contact quality (phone/email),
  website present (10), rating (15), review_count (15), services/social richness (20), penalise incomplete.
- If ANTHROPIC_API_KEY set: LLM (model claude-sonnet-4-6) gets lead JSON, returns strict JSON
  {score, qualification, reason}; blend/clamp with baseline; on any failure fall back to rule-based.
- Labels: Hot >=70, Warm 40-69, Cold <40, "Incomplete" if not is_complete (cap score at 39).
- reason must cite evidence (e.g. "4.8 rating, 540 reviews, has email+website").

## Stage 4 spec (dashboard/app.py)
- Streamlit: sidebar filters (qualification multiselect, score slider, source, completeness toggle, text search),
  summary metric cards (total, Hot/Warm/Cold/Incomplete, avg score), table (st.dataframe), CSV download of filtered view,
  lead detail expander showing provenance (verified vs AI-inferred), reads data/leads.csv (path override in sidebar).

## Stage 5
- README.md: setup, architecture diagram (ASCII), data source & compliance, scoring logic, dedup approach,
  limitations, how to run (commands below), sample output notes.
- Generate data/sample_leads.csv via `python -m leadgen.pipeline --source fixture --enrich? --score --out data/sample_leads.csv`
  (enrich offline-skips *.example sites). Clearly label sample as SYNTHETIC; tell user to replace with a real
  OSM/Places run before submitting.

## Commands
pip install -r requirements.txt
python -m pytest -q
python -m leadgen.pipeline --source fixture --out data/leads.csv
python -m leadgen.pipeline --source osm --location "Mumbai" --category "coworking space" --enrich --score --out data/leads.csv
python -m leadgen.pipeline --source places --max-results 60 --enrich --score --out data/leads.csv
streamlit run dashboard/app.py
