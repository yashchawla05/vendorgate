"""Form samples (data/form_samples/): each one, run through the real pipeline, gives its expected outcome."""
from pathlib import Path

import pytest

from core.documents.reader import DocumentContent
from core.llm.offline_provider import OfflineProvider
from core.models import COUNTRY_NAMES
from core.pipeline.runner import run_to_completion
from core.scenarios import check
from core.submissions import draft_from_folder, get_submission, list_form_samples

SAMPLES = list_form_samples()


def test_three_samples_per_country_with_clean_and_broken_cases():
    for country in COUNTRY_NAMES:
        mine = [s for s in SAMPLES if s["country"] == country]
        assert len(mine) == 3, country
        assert {s["expect"]["status"] for s in mine} >= {"APPROVED", "PENDING"}, country


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_sample_gives_its_expected_outcome(fresh_db, sample):
    sid, _ = run_to_completion(draft_from_folder(Path(sample["folder"]), "portal"))
    result = check({"dir": sample["id"], "expect": sample["expect"]}, get_submission(sid))
    assert result["ok"], result["problems"]


def test_offline_reader_finds_a_company_name_that_wraps_onto_the_next_line():
    text = ("Companies House (synthetic)\nCompany Number 18622069\nThe Registrar of Companies for England and "
            "Wales hereby certifies that ASHDOWN LEDGER LTD is\nthis day incorporated under the Companies Act 2006")
    result, _ = OfflineProvider().understand_document(
        DocumentContent(filename="upload", sha256="", kind="pdf", text=text), ["company_registration_certificate"])
    assert {f.name: f.value for f in result.fields}["company_name"] == "ASHDOWN LEDGER LTD"
