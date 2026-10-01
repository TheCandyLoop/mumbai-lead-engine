# Mumbai Coworking Lead Engine

A small, modular pipeline that **discovers** Mumbai coworking-space leads, **cleans and deduplicates** them,
**enriches** them from their public websites, assigns an **AI-assisted 0-100 qualification score**, and serves
the result in a **Streamlit dashboard** with CSV export.

> Built for the Yanisa AI Engineer Intern assignment (Google Maps Lead Discovery & Qualification).
> Design priorities: reliable data, explainable scoring, compliant data access, clean modular code.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then fill in keys you have (all optional)

# 1) offline demo (synthetic sample data, no keys, no network)
python -m leadgen.pipeline --source fixture --score --no-llm --out data/leads.csv

# 2) real run, free (OpenStreetMap)
python -m leadgen.pipeline --source osm --location "Mumbai" --category "coworking space" \
       --enrich --score --out data/leads.csv

# 3) real run, Google Places API (New)  -> needs GOOGLE_PLACES_API_KEY
python -m leadgen.pipeline --source places --location "Mumbai" --category "coworking space" \
       --max-results 60 --enrich --score --out data/leads.csv

# dashboard
streamlit run dashboard/app.py

# tests
python -m pytest -q
```

| Flag | Meaning |
|---|---|
| `--source places\|osm\|fixture` | discovery backend |
| `--enrich` | visit each lead's website for email / phone / socials / services |
| `--score` | compute score + qualification + reason |
| `--no-llm` | rule-based scoring only (skip Claude even if a key exists) |
| `--max-results N` | cap on discovered records |

Environment variables (`.env`): `GOOGLE_PLACES_API_KEY`, `ANTHROPIC_API_KEY`, `USER_AGENT`
(use a UA with your contact email; it is sent to OSM and to websites).

---

## Architecture

```
            +--------------------+
 location + | 1. DISCOVERY       |  places_api.py  (Google Places API New, Text Search)
 category ->|  discovery/*.py    |  osm.py         (Nominatim + Overpass)
            +---------+----------+  fixture.py     (offline synthetic sample)
                      | list[Lead]
            +---------v----------+
            | 2. CLEAN + DEDUPE  |  cleaning.py  E.164 phones, emails, URLs, names, pincode
            +---------+----------+               union-find dedup -> merge clusters
                      | list[Lead]  (+ is_complete flag, stable lead_id)
            +---------v----------+
            | 3. ENRICH          |  enrichment.py  robots-aware fetch -> parse_html()
            +---------+----------+                 email / phone / socials / services
                      |
            +---------v----------+
            | 4. QUALIFY         |  scoring.py  rule baseline  (+ optional Claude layer)
            +---------+----------+
                      |  CSV (io_utils.py)
            +---------v----------+
            | 5. DASHBOARD       |  dashboard/app.py  <-  leadgen/dashboard_utils.py (pure logic)
            +--------------------+
```

Every stage consumes and returns `list[Lead]` (`leadgen/models.py`), so stages are independent, individually
testable, and can be run or skipped from the CLI. `pipeline.py` is only the orchestrator.

```
leadgen/
  models.py            Lead dataclass (schema + provenance)
  config.py            env / constants
  discovery/           places_api.py, osm.py, fixture.py
  cleaning.py          normalization + dedup + lead_id
  enrichment.py        website enrichment
  scoring.py           qualification
  io_utils.py          CSV save/load
  dashboard_utils.py   filter / summary / export logic for the UI
  pipeline.py          CLI orchestrator
dashboard/app.py       Streamlit UI
tests/                 37 tests
data/                  sample_raw.json (synthetic input), sample_leads.csv (sample output)
CONTINUE.md            development handoff notes
```

---

## Data source and compliance

- **Google Places API (New), Text Search** is the official, permitted Google Maps data route. Requested fields:
  name, address, phone, website, Maps URL, rating, review count, primary type. Note: phone / website / rating are in
  Google's Enterprise SKU pricing tier; check your billing settings.
- **OpenStreetMap** (Nominatim geocoding + Overpass) is the free open-data alternative. It has fewer phones and no
  ratings, so Places gives richer leads and OSM gives free coverage.
- **No Google Maps page scraping, no CAPTCHA / login / anti-abuse bypass.** The code contains none.
- Website enrichment is deliberately polite: it checks `robots.txt` (a 401/403 on robots.txt means *do not crawl*),
  sends an identifying `User-Agent`, waits 1.5 s between requests, caps at 3 pages per site and 1.5 MB per page,
  reads HTML only, and skips social/aggregator sites (Facebook, Instagram, JustDial ...) whose terms prohibit scraping.
- Only public **business** contact details are collected.

### Mandatory lead rule
`company_name` **and** (`phone` **or** `email`). Leads failing this are kept but flagged `is_complete = False`,
labelled **Incomplete**, and capped at a score of 39 so they never look like good leads.

---

## Data model (output CSV)

`lead_id, company_name, category, address, phone, email, website, maps_url, rating, review_count, social_links,
services, lead_score, qualification, qualification_reason, source, collected_at, is_complete, merged_from, provenance`

- `phone` is E.164 (`+912240001111`); `email` lowercase and validated; `website` normalized (no `www`, no trailing `/`).
- `source` shows where data came from; merged records show e.g. `osm+google_places`.
- `lead_id` is a stable hash (phone, else website domain, else name+pincode), so reruns give the same ids.
- `social_links`, `services`, `provenance` are JSON in the CSV.

### Verified vs AI-inferred
Every value carries a provenance tag in the `provenance` column, shown in the dashboard detail panel:

| Tag | Meaning |
|---|---|
| `verified` | came from the discovery source or literally appears on the business's own website |
| `rule_based` | deterministic computation from verified fields (the baseline score and its reason) |
| `ai_inferred` | produced by the LLM (score / reason when the Claude layer was used) |

Enrichment never uses an LLM, so scraped fields are always `verified`; AI involvement is limited to the score and reason.

---

## Cleaning and deduplication

Normalization: phones via `phonenumbers` (region IN, E.164, invalid text such as "not available" dropped),
emails lowercased / validated, URLs canonicalized, names whitespace-cleaned, pincode extracted from addresses.

Dedup is a **union-find over pairwise match rules**, then each cluster is merged. Two records are the same business if:

1. same normalized **phone**; or
2. same **email**, or same website **domain** (social/aggregator domains ignored), **unless both addresses carry
   different pincodes** (multi-branch brands share a domain/email but are different leads); or
3. **fuzzy name** (`rapidfuzz` token-sort >= 88 after stripping Pvt/Ltd/etc.) **and** a matching pincode or similar address.

Merging keeps the richest record as the base and fills its gaps (phone, email, website, social links...) from the
others, recording `merged_from`. Example from the sample data: *Skyline Cowork Bandra* (website + phone) and
*Skyline Cowork - Bandra* (email + same phone) collapse into one lead with all three fields, while *Skyline Cowork
Powai* (same domain, different pincode) stays separate.

Pairwise comparison is O(n^2), fine for the hundreds of leads this targets; use blocking (by pincode) if scaling to
tens of thousands.

---

## Enrichment

For each lead with a real website: fetch the home page, plus the contact and about pages found via its links.
Extracts **emails** (mailto + text; junk like image names filtered; same-domain and `info@` / `hello@` ranked first),
**phones** (`tel:` + Indian number patterns, validated), **social links** (LinkedIn, Facebook, Instagram, X, YouTube;
share buttons and bare homepages ignored) and **services** by literal keyword match (hot desk, dedicated desk, private
office, meeting room, day pass, virtual office, event space, 24/7 access, cafeteria, wifi, parking).
Existing values are never overwritten, and a site that fails is skipped without affecting the run.
Enrichment can turn an incomplete lead complete (e.g. an email found on the website).

---

## Scoring logic

**Assumed target:** leads that are *reachable*, *established*, *digitally present* and *clear about services*.

**1. Rule-based baseline (always runs, fully explainable), 100 points:**

| Component | Max | Rule |
|---|---|---|
| Contact | 30 | phone 15 + email 15 |
| Website | 10 | own website (a Facebook page does not count) |
| Rating | 15 | >=4.5: 15, >=4.0: 11, >=3.5: 7, else 3 |
| Reviews | 15 | >=300: 15, >=100: 12, >=30: 8, >=10: 5, >0: 2 |
| Services | 15 | 3 per service found, capped |
| Social | 10 | LinkedIn 4, other networks 3 each, capped |
| Address | 5 | present |

**2. Optional LLM layer (Claude, needs `ANTHROPIC_API_KEY`, `--no-llm` disables it):** receives only structured
fields (flags such as `has_phone`; raw phone/email and scraped web text are **not** sent, which removes the
prompt-injection surface), returns `{score, reason}` as JSON. Guardrails: the output is validated; the score may differ
from the baseline by at most **+-15**; incomplete leads stay capped at 39; any API / parse failure falls back to the baseline.

**Labels are always derived from the final score**, never taken from the model:
**Hot** >= 70, **Warm** 40-69, **Cold** < 40, **Incomplete** if the mandatory rule fails.

`qualification_reason` cites evidence, e.g. *"Hot (75/100): 4.6 rating from 312 reviews; has phone+email+website"*.

---

## Dashboard

`streamlit run dashboard/app.py` -- filters (qualification, score range, source, complete-only, has phone / email /
website, text search over name, address and services), summary counts (shown / Hot / Warm / Cold / Incomplete / average
score), qualification chart, sortable table with score bars and website links, **filtered CSV download**, and a lead
detail panel showing the provenance of each field. It loads `data/leads.csv` (falling back to `data/sample_leads.csv`)
or any uploaded CSV.

---

## Testing

`python -m pytest -q` runs 37 tests: normalization and dedup (including the multi-branch case), the HTML parser,
the real fetcher against a local HTTP server (robots.txt, content-type, 404s), scoring and LLM guardrails with fake
LLM callables, the Places and OSM adapters with realistic payloads and mocked HTTP, dashboard filters, and a headless
Streamlit smoke test.

---

## Limitations

- **Sample data is synthetic.** `data/sample_raw.json` / `data/sample_leads.csv` contain fictional businesses so the
  project runs offline. Replace them with a real run before relying on any figures.
- **Live paths were developed against documented API shapes and mocked HTTP.** The Places API, Overpass and real
  websites are not exercised in the automated tests, so expect small tweaks when first run against live data.
- **OSM coverage is thin for Indian coworking spaces**, with many entries lacking phones, so many leads will come out
  Incomplete. Combining Places with OSM (or enrichment) gives better completeness.
- **Places API returns up to about 60 results per query**; for wider coverage run several queries (neighbourhoods:
  "coworking space in Andheri", "...in Powai", ...) and concatenate them into the dedup stage.
- **Dedup edge cases:** a shared central phone number merges branches; names with no address data can false-merge.
  Review `merged_from > 1` rows if precision matters.
- **Enrichment is HTML-only**: JavaScript-rendered sites, contact forms and email obfuscation are missed; services
  are keyword matches, not understanding. Emails scraped from a page are not mailbox-verified.
- **Scoring is heuristic.** The weights encode one assumption about a "good" lead and are not trained on conversion data.
- Sequential, rate-limited fetching is intentionally slow (about 2-6 s per site).

## Possible improvements
Multi-query / grid discovery, blocking in dedup, async fetching with per-host limits, email MX validation, LLM
extraction of services from site text (tagged `ai_inferred`), learning weights from outcome data, scheduled refresh.
