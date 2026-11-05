"""Sanity checks on the committed synthetic data (run scripts/generate_data.py to rebuild)."""
import json

from core.config import DATA_DIR, EVAL_DIR, SCENARIO_DIR, VENDOR_SEED_FILE
from core.models import SubmissionForm
from core.validators import india, us


def test_vendor_master_ids_are_structurally_valid():
    vendors = json.loads(VENDOR_SEED_FILE.read_text())
    assert len(vendors) == 12
    for v in vendors:
        if v["country"] == "IN":
            assert india.validate_pan(v["pan"]).ok
            if v["gstin"]:
                assert india.validate_gstin(v["gstin"]).ok
            assert india.validate_ifsc(v["bank_code"]).ok
        if v["country"] == "US":
            assert us.validate_ein(v["ein"]).ok and us.validate_aba(v["bank_code"]).ok


def test_synthetic_ids_use_the_zz_series():
    # No real PANs: every synthetic PAN starts with 'ZZ'.
    for v in json.loads(VENDOR_SEED_FILE.read_text()):
        if v["pan"]:
            assert v["pan"].startswith("ZZ")


def test_every_scenario_step_has_a_valid_submission():
    scenarios = sorted(p for p in SCENARIO_DIR.iterdir() if p.is_dir())
    assert {p.name for p in scenarios} >= {"happy", "e1_looks_fine", "e2_wrong_docs", "e3_ghost_vendor",
                                           "e4_fix_approved", "e4b_bank_change"}
    for folder in scenarios:
        meta = json.loads((folder / "scenario.json").read_text())
        for step in meta["steps"]:
            form = SubmissionForm.model_validate_json((folder / step["dir"] / "submission.json").read_text())
            for doc in form.documents:
                assert (folder / step["dir"] / doc.filename).exists()


def test_ground_truth_files_exist():
    truth = json.loads((EVAL_DIR / "ground_truth.json").read_text())
    assert len(truth) > 50
    scans = [k for k, v in truth.items() if "scan" in v["layout"]]
    assert len(scans) >= 2
    for rel in truth:
        assert (DATA_DIR / rel).exists(), rel
