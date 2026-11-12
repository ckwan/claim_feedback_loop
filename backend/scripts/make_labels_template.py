"""
One-time helper: expands data/eval_labels_template.json into one blank
label entry per case in data/synthetic_denial_cases.json, so you're hand-
labeling against the real claim_ids instead of typing them by hand.

Usage:
    python scripts/make_labels_template.py
Writes data/eval_labels.json (won't overwrite if it already exists).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "data" / "synthetic_denial_cases.json"
LABELS_PATH = ROOT / "data" / "eval_labels.json"


def main() -> None:
    if LABELS_PATH.exists():
        print(f"{LABELS_PATH} already exists - not overwriting. Delete it first if you want a fresh template.")
        return

    cases = json.loads(CASES_PATH.read_text())
    labels = [
        {
            "claim_id": case["claim_id"],
            # Fill these in by hand. should_appeal: true/false. Leave null
            # (or just delete the entry) for cases you're skipping - the
            # eval script only scores cases that have a non-null label.
            "should_appeal": None,
            "strongest_ground": "",
            "notes": "",
        }
        for case in cases
    ]
    LABELS_PATH.write_text(json.dumps(labels, indent=2))
    print(f"Wrote {len(labels)} blank label entries to {LABELS_PATH}")
    print("Fill in should_appeal (true/false) and strongest_ground for 30-50 of these, then run the eval.")


if __name__ == "__main__":
    main()
