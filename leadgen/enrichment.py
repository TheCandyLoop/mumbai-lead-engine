"""Website enrichment: emails, phones, social links, services.

Design
- `parse_html(html, base_url)` is PURE (no network) -> easy to test.
- `Fetcher` does the polite network part: robots.txt, User-Agent, delay, timeout,
  size cap, HTML only, max 3 pages/site (home + contact + about).
- Anything extracted from a page is tagged provenance="verified" (it literally appears
  on the business's own site). Nothing here is LLM-guessed; AI-inferred tags come from Stage 3.
- Existing values from the discovery source are never overwritten.
- A failing site never stops the run.
"""
from __future__ import annotations
import logging
import re
import time
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from leadgen import config
from leadgen.cleaning import SOCIAL_DOMAINS, domain, norm_email, norm_phone
from leadgen.models import Lead

log = logging.getLogger("enrichment")

MAX_PAGES = 3
MAX_BYTES = 1_500_000
RESERVED_TLDS = (".example", ".invalid", ".test", ".localhost")
JUNK_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$|sentry|wixpress|domain\.com|yourdomain|example\.com", re.I)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+91[\s\-]?)?(?:[6-9]\d{4}[\s\-]?\d{5}|0?22[\s\-]?\d{4}[\s\-]?\d{4})")
PREFERRED_PREFIX = ("info", "hello", "contact", "sales", "enquir", "inquir", "support", "team", "bookings")

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "instagram.com": "instagram",
    "twitter.com": "twitter", "x.com": "twitter", "youtube.com": "youtube",
}
SHARE_HINTS = ("sharer", "intent/", "share?", "/share", "login", "dialog/")

SERVICE_KEYWORDS = {
    "hot desk": ["hot desk", "hotdesk", "flexi desk", "flex desk"],
    "dedicated desk": ["dedicated desk", "fixed desk"],
    "private office": ["private office", "private cabin", "managed office", "private cabins"],
    "meeting room": ["meeting room", "conference room", "boardroom"],
    "day pass": ["day pass"],
    "virtual office": ["virtual office"],
    "event space": ["event space", "event hall", "training room"],
    "24/7 access": ["24/7", "24x7", "round the clock"],
    "cafeteria": ["cafeteria", "cafe ", "pantry", "free coffee"],
    "high-speed wifi": ["high-speed wifi", "high speed wifi", "high-speed internet", "fibre"],
    "parking": ["parking"],
}


# ---------------------------------------------------------------- pure parsing
def parse_html(html: str, base_url: str = "") -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    site_domain = domain(base_url)

    # emails
    cand: list[str] = []
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            cand.append(a["href"][7:].split("?")[0])
    cand += EMAIL_RE.findall(text)
    emails: list[str] = []
    for c in cand:
        e = norm_email(c)
        if e and not JUNK_EMAIL.search(e) and e not in emails:
            emails.append(e)
    emails.sort(key=lambda e: (
        0 if site_domain and e.split("@")[1].endswith(site_domain) else 1,
        0 if e.split("@")[0].startswith(PREFERRED_PREFIX) else 1,
    ))

    # phones
    pc: list[str] = [a["href"][4:] for a in soup.find_all("a", href=True) if a["href"].lower().startswith("tel:")]
    pc += PHONE_RE.findall(text)
    phones: list[str] = []
    for p in pc:
        n = norm_phone(p)
        if n and n not in phones:
            phones.append(n)

    # socials
    socials: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if any(h in href.lower() for h in SHARE_HINTS):
            continue
        host = urlparse(href).netloc.lower().removeprefix("www.")
        for sd, net in SOCIAL_HOSTS.items():
            if host == sd or host.endswith("." + sd):
                path = urlparse(href).path.strip("/")
                if path:  # skip bare homepage links
                    socials.setdefault(net, href.split("?")[0].rstrip("/"))

    # services (literal keyword match -> verifiable on the page)
    low = text.lower()
    services = [name for name, kws in SERVICE_KEYWORDS.items() if any(k in low for k in kws)]

    # internal links worth visiting
    contact_link = about_link = ""
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if domain(href) != site_domain:
            continue
        path = urlparse(href).path.lower()
        if not contact_link and "contact" in path:
            contact_link = href
        elif not about_link and "about" in path:
            about_link = href

    title = soup.title.get_text(strip=True) if soup.title else ""
    return {"emails": emails, "phones": phones, "socials": socials, "services": services,
            "contact_link": contact_link, "about_link": about_link, "title": title}


# ---------------------------------------------------------------- network
class Fetcher:
    def __init__(self, delay: float = 1.5, timeout: int = 15):
        self.delay, self.timeout = delay, timeout
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last = 0.0
        self.headers = {"User-Agent": config.USER_AGENT}

    def _sleep(self):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                self._sleep()
                r = requests.get(root + "/robots.txt", headers=self.headers, timeout=self.timeout)
                if r.status_code in (401, 403):
                    rp = None          # access restricted -> be conservative, don't crawl
                elif r.status_code >= 400:
                    rp.parse([])       # no robots.txt -> allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.parse([])
            self._robots[root] = rp
        rp = self._robots[root]
        return bool(rp and rp.can_fetch(config.USER_AGENT, url))

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            log.info("robots.txt disallows %s", url)
            return None
        try:
            self._sleep()
            r = requests.get(url, headers=self.headers, timeout=self.timeout, stream=True)
            if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "").lower():
                return None
            raw = r.raw.read(MAX_BYTES, decode_content=True)
            return raw.decode(r.encoding or "utf-8", errors="ignore")
        except requests.RequestException as e:
            log.info("fetch failed %s: %s", url, e)
            return None


# ---------------------------------------------------------------- orchestration
def _skippable(url: str) -> bool:
    d = domain(url)
    return (not d) or d in SOCIAL_DOMAINS or d.endswith(RESERVED_TLDS) or any(d.endswith("." + s) for s in SOCIAL_DOMAINS)


def apply_enrichment(lead: Lead, parsed: dict) -> list[str]:
    """Merge parsed website data into the lead without overwriting. Returns list of fields filled."""
    filled = []
    if not lead.email and parsed["emails"]:
        lead.email = parsed["emails"][0]; lead.provenance["email"] = "verified"; filled.append("email")
    if not lead.phone and parsed["phones"]:
        lead.phone = parsed["phones"][0]; lead.provenance["phone"] = "verified"; filled.append("phone")
    for net, url in parsed["socials"].items():
        if net not in lead.social_links:
            lead.social_links[net] = url
            lead.provenance[f"social_{net}"] = "verified"
            filled.append(f"social_{net}")
    new_services = [s for s in parsed["services"] if s not in lead.services]
    if new_services:
        lead.services.extend(new_services)
        lead.provenance["services"] = "verified"
        filled.append("services")
    lead.is_complete = bool(lead.company_name and (lead.phone or lead.email))
    return filled


def _merge_parsed(acc: dict, new: dict) -> dict:
    for k in ("emails", "phones", "services"):
        acc[k] += [x for x in new[k] if x not in acc[k]]
    for n, u in new["socials"].items():
        acc["socials"].setdefault(n, u)
    return acc


def enrich_lead(lead: Lead, fetcher: Fetcher) -> list[str]:
    if _skippable(lead.website):
        return []
    acc = {"emails": [], "phones": [], "socials": {}, "services": []}
    home = fetcher.get(lead.website)
    if home is None:
        return []
    first = parse_html(home, lead.website)
    _merge_parsed(acc, first)
    extra = [u for u in (first["contact_link"], first["about_link"]) if u][: MAX_PAGES - 1]
    for u in extra:
        html = fetcher.get(u)
        if html:
            _merge_parsed(acc, parse_html(html, lead.website))
    return apply_enrichment(lead, acc)


def enrich_leads(leads: list[Lead], fetcher: Fetcher | None = None) -> list[Lead]:
    fetcher = fetcher or Fetcher()
    n_sites = n_ok = 0
    for l in leads:
        if not l.website or _skippable(l.website):
            continue
        n_sites += 1
        try:
            if enrich_lead(l, fetcher):
                n_ok += 1
        except Exception as e:  # never let one site kill the run
            log.warning("enrichment error for %s: %s", l.company_name, e)
    log.info("enrichment: %d sites tried, %d enriched", n_sites, n_ok)
    return leads
