"""Build SubmissionDrafts from folders (scenarios, history, programmatic JSON) and read back stored runs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core import db
from core.config import FORM_SAMPLE_DIR, SCENARIO_DIR
from core.models import COUNTRY_NAMES, SubmissionForm
from core.pipeline.context import SubmissionDraft


def draft_from_folder(folder: Path, source: str, *, parent_id: str | None = None, token: str | None = None,
                      submitted_at: datetime | None = None, seeded: bool = False) -> SubmissionDraft:
    """A folder holds submission.json (the SubmissionForm) plus the files it lists."""
    form = SubmissionForm.model_validate_json((folder / "submission.json").read_text())
    files = {d.slot: (d.filename, (folder / d.filename).read_bytes()) for d in form.documents}
    return SubmissionDraft(form=form, files=files, source=source, parent_id=parent_id, token=token,
                           submitted_at=submitted_at, seeded=seeded)


def list_scenarios() -> list[dict]:
    out = []
    # Happy path first (the demo opens with it), then edge cases in order.
    folders = sorted((p for p in SCENARIO_DIR.iterdir() if (p / "scenario.json").exists()),
                     key=lambda p: (p.name != "happy", p.name))
    for folder in folders:
        out.append(json.loads((folder / "scenario.json").read_text()) | {"folder": str(folder)})
    return out


def load_scenario(scenario_id: str) -> dict:
    folder = SCENARIO_DIR / scenario_id
    return json.loads((folder / "scenario.json").read_text()) | {"folder": str(folder)}


def list_form_samples() -> list[dict]:
    """Pre-filled inputs for the manual form: data/form_samples/<id>/ (sample.json, submission.json, files)."""
    if not FORM_SAMPLE_DIR.exists():
        return []
    metas = [json.loads((p / "sample.json").read_text()) | {"folder": str(p)}
             for p in FORM_SAMPLE_DIR.iterdir() if (p / "sample.json").exists()]
    countries = list(COUNTRY_NAMES)
    return sorted(metas, key=lambda m: (countries.index(m["country"]) if m["country"] in countries else 99, m["id"]))


def get_submission(submission_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if not row:
        return None
    row["form"] = json.loads(row["form_json"])
    row["documents"] = db.query("SELECT * FROM documents WHERE submission_id = ? ORDER BY id", (submission_id,))
    row["findings"] = db.query("SELECT * FROM findings WHERE submission_id = ? ORDER BY id", (submission_id,))
    row["stages"] = db.query("SELECT * FROM stage_runs WHERE submission_id = ? ORDER BY id", (submission_id,))
    row["decision"] = db.query_one("SELECT * FROM decisions WHERE submission_id = ?", (submission_id,))
    row["outbox"] = db.query("SELECT * FROM outbox WHERE submission_id = ? ORDER BY id", (submission_id,))
    row["reviews"] = db.query("SELECT * FROM review_actions WHERE submission_id = ? ORDER BY id", (submission_id,))
    row["chain"] = db.query("SELECT id, version, status, sub_status, submitted_at FROM submissions WHERE chain_id = ?"
                            " ORDER BY version", (row["chain_id"],))
    for key in ("findings",):
        for f in row[key]:
            f["evidence"] = json.loads(f.pop("evidence_json") or "{}")
    for s in row["stages"]:
        s["details"] = json.loads(s.pop("details_json") or "{}")
    for d in row["documents"]:
        d["fields"] = json.loads(d.pop("fields_json") or "{}")
    return row
