"""CLI orchestrator.  Stages: discover -> clean/dedupe -> [enrich] -> [score] -> save.

Example:
  python -m leadgen.pipeline --source fixture
  python -m leadgen.pipeline --source osm --location "Mumbai" --category "coworking space"
  python -m leadgen.pipeline --source places --max-results 60
"""
from __future__ import annotations
import argparse
import json
import logging

from leadgen.cleaning import clean_and_dedupe
from leadgen.io_utils import save_leads

log = logging.getLogger("pipeline")


def get_source(name: str):
    if name == "places":
        from leadgen.discovery import places_api as m
    elif name == "osm":
        from leadgen.discovery import osm as m
    elif name == "fixture":
        from leadgen.discovery import fixture as m
    else:
        raise ValueError(name)
    return m


def run(source: str, location: str, category: str, max_results: int, out: str,
        enrich: bool = False, score: bool = False, use_llm: bool = True) -> dict:
    raw = get_source(source).discover(location, category, max_results)
    log.info("discovered %d raw records from %s", len(raw), source)
    leads, stats = clean_and_dedupe(raw)

    if enrich:  # Stage 2
        from leadgen.enrichment import enrich_leads
        before = stats["complete"]
        leads = enrich_leads(leads)
        stats["complete"] = sum(l.is_complete for l in leads)
        stats["incomplete"] = len(leads) - stats["complete"]
        stats["made_complete_by_enrichment"] = stats["complete"] - before
    if score:   # Stage 3
        from leadgen.scoring import score_leads
        leads = score_leads(leads, use_llm=use_llm)
        stats["by_qualification"] = {q: sum(l.qualification == q for l in leads)
                                     for q in ("Hot", "Warm", "Cold", "Incomplete")}

    save_leads(leads, out)
    log.info("saved %d leads -> %s | %s", len(leads), out, json.dumps(stats))
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["places", "osm", "fixture"], default="fixture")
    ap.add_argument("--location", default="Mumbai")
    ap.add_argument("--category", default="coworking space")
    ap.add_argument("--max-results", type=int, default=200)
    ap.add_argument("--out", default="data/leads.csv")
    ap.add_argument("--enrich", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="rule-based scoring only")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(run(a.source, a.location, a.category, a.max_results, a.out, a.enrich, a.score, not a.no_llm), indent=2))


if __name__ == "__main__":
    main()
