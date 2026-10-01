from leadgen.cleaning import (norm_phone, norm_email, norm_url, clean_and_dedupe, name_key)
from leadgen.discovery import fixture
from leadgen.models import Lead


def test_phone_normalization():
    assert norm_phone("022-40001111") == "+912240001111"
    assert norm_phone("+91 98200 11223") == "+919820011223"
    assert norm_phone("not available") == ""
    assert norm_phone("") == ""


def test_email_url():
    assert norm_email("INFO@Workloft.example") == "info@workloft.example"
    assert norm_email("bad@@x") == ""
    assert norm_url("www.workloft.example/") == "https://workloft.example"


def test_name_key_strips_noise():
    assert name_key("HiveSpace Andheri Pvt Ltd") == name_key("HiveSpace Andheri")


def test_dedupe_and_merge_on_fixture():
    leads, stats = clean_and_dedupe(fixture.discover())
    names = [l.company_name for l in leads]
    assert stats["dropped_no_name"] == 1
    assert sum("HiveSpace" in n for n in names) == 1
    assert sum("Skyline Cowork" in n and "Powai" not in n for n in names) == 1  # Bandra dupes merged
    assert any("Powai" in n for n in names)  # different branch must survive
    sky = next(l for l in leads if "Bandra" in l.company_name and "Skyline" in l.company_name)
    assert sky.phone and sky.email and sky.website  # merged fields
    assert sky.merged_from == 2


def test_completeness_rule():
    leads, _ = clean_and_dedupe(fixture.discover())
    ghost = next(l for l in leads if l.company_name == "Ghost Listing")
    bkc = next(l for l in leads if "BKC" in l.company_name)
    assert not ghost.is_complete and not bkc.is_complete  # no phone/email
    wl = next(l for l in leads if "Workloft" in l.company_name)
    assert wl.is_complete  # email only is enough


def test_unique_ids():
    leads, _ = clean_and_dedupe(fixture.discover())
    assert len({l.lead_id for l in leads}) == len(leads)
