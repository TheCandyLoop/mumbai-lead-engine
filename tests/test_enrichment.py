from leadgen.enrichment import parse_html, apply_enrichment, enrich_leads, enrich_lead, _skippable
from leadgen.models import Lead

HTML = """
<html><head><title>HiveSpace</title><script>var a='x@sentry.io'</script></head><body>
<a href="mailto:Hello@hivespace.in?subject=Hi">Mail</a> also sales@hivespace.in and logo@2x.png
<a href="tel:+91 98200 11223">Call</a> Office: 022 4000 1111
<a href="https://www.linkedin.com/company/hivespace/">in</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>
<a href="https://instagram.com/">home only</a>
<a href="https://instagram.com/hivespace_in?hl=en">ig</a>
<p>We offer hot desks, private cabins, meeting rooms, and day pass. Open 24/7. Free parking.</p>
<a href="/contact-us">Contact</a> <a href="/about">About</a> <a href="https://other.com/contact">x</a>
</body></html>
"""


def test_parse_html():
    r = parse_html(HTML, "https://hivespace.in")
    assert r["emails"][0] == "hello@hivespace.in" and "logo@2x.png" not in r["emails"]
    assert not any("sentry" in e for e in r["emails"])
    assert "+919820011223" in r["phones"] and "+912240001111" in r["phones"]
    assert r["socials"]["linkedin"] == "https://www.linkedin.com/company/hivespace"
    assert r["socials"]["instagram"] == "https://instagram.com/hivespace_in"
    assert "facebook" not in r["socials"]            # share link ignored
    for s in ("hot desk", "private office", "meeting room", "day pass", "24/7 access", "parking"):
        assert s in r["services"]
    assert r["contact_link"] == "https://hivespace.in/contact-us"
    assert r["about_link"] == "https://hivespace.in/about"


def test_apply_does_not_overwrite_and_tags_provenance():
    l = Lead(company_name="X", phone="+919820011223", website="https://hivespace.in")
    filled = apply_enrichment(l, parse_html(HTML, "https://hivespace.in"))
    assert l.phone == "+919820011223"                 # kept
    assert l.email == "hello@hivespace.in" and l.provenance["email"] == "verified"
    assert "email" in filled and l.is_complete
    assert l.provenance["services"] == "verified"


def test_skip_reserved_and_social_domains():
    assert _skippable("https://foo.example")
    assert _skippable("https://facebook.com/gridspaces")
    assert not _skippable("https://hivespace.in")


class FakeFetcher:
    def __init__(self, pages): self.pages = pages
    def get(self, url): return self.pages.get(url)


def test_enrich_lead_with_fake_fetcher_and_failures():
    pages = {"https://hivespace.in": HTML,
             "https://hivespace.in/contact-us": "<p>Mail us at team@hivespace.in</p>"}
    ok = Lead(company_name="A", website="https://hivespace.in")
    bad = Lead(company_name="B", website="https://down.in")
    skip = Lead(company_name="C", website="https://foo.example")
    enrich_leads([ok, bad, skip], fetcher=FakeFetcher(pages))
    assert ok.email and "linkedin" in ok.social_links and ok.services
    assert not bad.email and not skip.email           # failure / skip are harmless
