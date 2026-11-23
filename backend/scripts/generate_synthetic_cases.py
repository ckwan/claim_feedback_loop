"""
Generates synthetic claim-denial-appeal cases for Week 1/2 of the
LangGraph/Temporal rebuild: no real PHI, template-based, fully offline (no
LLM calls — this is fixture data, not AI-generated content, so there's
nothing to validate against a model and no API key required to run it).

Usage:
    python scripts/generate_synthetic_cases.py
Writes data/synthetic_denial_cases.json (60 cases by default).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(42)  # deterministic output — reruns don't silently change the eval set

FIRST_NAMES = [
    "Maria", "James", "Linda", "Robert", "Patricia", "Michael", "Jennifer",
    "David", "Susan", "William", "Karen", "Richard", "Nancy", "Joseph",
    "Betty", "Thomas", "Sandra", "Charles", "Margaret", "Daniel",
]
LAST_NAMES = [
    "Garcia", "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
]

POLICY_TYPES = ["auto", "home", "renters", "umbrella"]

# Each denial reason pairs with a code, a policy excerpt template, and a set
# of claim-fact templates — some facts genuinely support the denial, some
# are templated to plausibly *not* support it, to give the eval labelers
# (Week 2) real cases to disagree on, not just obvious yes/no.
DENIAL_SCENARIOS = [
    {
        "code": "LATE_NOTICE",
        "reason": "Claim was not reported within the policy's required notice period.",
        "policy_excerpt": (
            "Section 4.2 (Prompt Notice): The policyholder must notify the "
            "insurer of any loss within 30 days of the date of loss. Claims "
            "reported after this period may be denied unless the delay was "
            "reasonable and did not prejudice the insurer's investigation."
        ),
        "fact_templates": [
            "{name} reported the {policy_type} loss {days} days after it occurred, citing a hospital stay that prevented earlier contact.",
            "{name} reported the {policy_type} loss {days} days after it occurred with no stated reason for the delay.",
            "{name} reported the {policy_type} loss {days} days after it occurred; the insurer's adjuster confirmed the delay did not affect the investigation.",
        ],
        "days_range": (31, 90),
    },
    {
        "code": "PRE_EXISTING_DAMAGE",
        "reason": "Damage is assessed as pre-existing and not caused by the incident described.",
        "policy_excerpt": (
            "Section 6.1 (Covered Perils): This policy covers sudden and "
            "accidental loss. Damage that existed prior to the policy period, "
            "or that resulted from gradual deterioration, is excluded."
        ),
        "fact_templates": [
            "{name} filed a claim for {policy_type} damage; the inspection photos show rust consistent with gradual wear predating the policy.",
            "{name} filed a claim for {policy_type} damage immediately after a documented storm event in the area, with no prior inspection noting the damage.",
            "{name} filed a claim for {policy_type} damage; the prior year's renewal inspection report explicitly noted this damage already existed.",
        ],
        "days_range": None,
    },
    {
        "code": "EXCLUDED_PERIL",
        "reason": "The cause of loss falls under a specific policy exclusion.",
        "policy_excerpt": (
            "Section 7.3 (Exclusions): This policy does not cover loss caused "
            "directly or indirectly by flood, earth movement, or war, "
            "regardless of any other cause contributing concurrently."
        ),
        "fact_templates": [
            "{name}'s {policy_type} claim describes water damage from rising floodwater during a regional flood event.",
            "{name}'s {policy_type} claim describes water damage from a burst interior pipe, unrelated to any flood or weather event.",
            "{name}'s {policy_type} claim describes water damage, and the adjuster's report is ambiguous about whether the source was a pipe or ground water intrusion.",
        ],
        "days_range": None,
    },
    {
        "code": "COVERAGE_LAPSE",
        "reason": "Policy had lapsed for non-payment at the time of the loss.",
        "policy_excerpt": (
            "Section 2.4 (Grace Period): Coverage continues for 10 days after "
            "a missed premium payment. If payment is not received within "
            "that period, coverage terminates retroactively to the due date."
        ),
        "fact_templates": [
            "{name}'s premium was due on the 1st and unpaid; the loss occurred on day {days} after the due date, past the grace period.",
            "{name}'s premium was due on the 1st and paid on day 6, within the grace period; the loss occurred on day {days} after the due date.",
            "{name}'s premium payment was received on time, but the insurer's records show a processing delay that incorrectly flagged the account as lapsed.",
        ],
        "days_range": (1, 15),
    },
    {
        "code": "INSUFFICIENT_DOCUMENTATION",
        "reason": "Claimant did not provide sufficient documentation to substantiate the loss amount.",
        "policy_excerpt": (
            "Section 5.1 (Proof of Loss): The policyholder must provide "
            "itemized documentation of the claimed loss, including receipts "
            "or appraisals, within 60 days of the insurer's request."
        ),
        "fact_templates": [
            "{name} submitted no receipts or appraisal for the claimed {policy_type} loss despite two written requests from the insurer.",
            "{name} submitted a contractor estimate and photos for the claimed {policy_type} loss, which the adjuster's notes describe as 'incomplete' without specifying what was missing.",
            "{name} submitted itemized receipts for the claimed {policy_type} loss; the claim file shows these were received before the denial was issued.",
        ],
        "days_range": None,
    },
    {
        "code": "MISREPRESENTATION",
        "reason": "Application contained a material misrepresentation affecting coverage.",
        "policy_excerpt": (
            "Section 1.5 (Material Misrepresentation): Any material "
            "misrepresentation on the application, discovered at any time, "
            "voids coverage for claims related to the misrepresented fact."
        ),
        "fact_templates": [
            "{name} listed the {policy_type} property as owner-occupied on the application; inspection after the loss confirmed it was a rental unit.",
            "{name} listed the {policy_type} property as owner-occupied on the application, which matches the loss-date inspection; the insurer's flag appears to be a records error.",
            "{name}'s application answer in question is unrelated to the cause of this loss, though it may be inaccurate on an unrelated point.",
        ],
        "days_range": None,
    },
]


def _make_case(case_id: int) -> dict:
    scenario = random.choice(DENIAL_SCENARIOS)
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    policy_type = random.choice(POLICY_TYPES)
    days = random.randint(*scenario["days_range"]) if scenario["days_range"] else None

    fact_template = random.choice(scenario["fact_templates"])
    claim_facts = fact_template.format(name=name, policy_type=policy_type, days=days)

    return {
        "claim_id": f"SYN-{case_id:04d}",
        "org_id": "synthetic-org-001",
        "policyholder_name": name,
        "policy_type": policy_type,
        "claim_amount": round(random.uniform(500, 25000), 2),
        "claim_facts": claim_facts,
        "denial_reason": scenario["reason"],
        "denial_code": scenario["code"],
        "policy_excerpt": scenario["policy_excerpt"],
    }


def main(n: int = 60) -> None:
    cases = [_make_case(i + 1) for i in range(n)]

    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "synthetic_denial_cases.json"
    out_path.write_text(json.dumps(cases, indent=2))

    by_code: dict[str, int] = {}
    for c in cases:
        by_code[c["denial_code"]] = by_code.get(c["denial_code"], 0) + 1

    print(f"Wrote {len(cases)} cases to {out_path}")
    print("Distribution by denial_code:")
    for code, count in sorted(by_code.items()):
        print(f"  {code}: {count}")


if __name__ == "__main__":
    main()
