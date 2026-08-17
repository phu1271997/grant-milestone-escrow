"""Pure unit tests for the logic that turns observations into money.

These touch no storage, no network and no consensus. If the tier table is wrong
everything downstream is wrong, so it is pinned here in isolation where a
failure points straight at the rule rather than at the plumbing.
"""

import pytest


BANDS = dict(
    substantial_permille=750,
    partial_permille=500,
    substantial_payout_bps=7500,
    partial_payout_bps=5000,
)


@pytest.fixture()
def escrow_module(modules):
    return modules["escrow"]


def derive(escrow_module, met, total, blockers=0, gaps=0):
    return escrow_module._derive_settlement(met, total, blockers, gaps, **BANDS)


# ---------------------------------------------------------------------------
# Tier bands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "met,total,expected_tier,expected_bps",
    [
        (4, 4, "COMPLETE", 10000),
        (3, 4, "SUBSTANTIAL", 7500),
        (2, 4, "PARTIAL", 5000),
        (1, 4, "INSUFFICIENT", 0),
        (0, 4, "INSUFFICIENT", 0),
        # Eight requirements: the bands are ratios, not counts.
        (8, 8, "COMPLETE", 10000),
        (7, 8, "SUBSTANTIAL", 7500),
        (6, 8, "SUBSTANTIAL", 7500),
        (5, 8, "PARTIAL", 5000),
        (4, 8, "PARTIAL", 5000),
        (3, 8, "INSUFFICIENT", 0),
    ],
)
def test_tier_bands(escrow_module, met, total, expected_tier, expected_bps):
    assert derive(escrow_module, met, total) == (expected_tier, expected_bps)


def test_band_edges_use_integer_division(escrow_module):
    """2 of 3 is 666 permille — below the 750 band, inside the 500 band.

    Worth pinning explicitly: a float implementation rounding 0.667 upward would
    move a third of the milestone's money.
    """
    assert derive(escrow_module, 2, 3) == ("PARTIAL", 5000)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_gaps_outrank_everything(escrow_module):
    """Even a perfect score yields nothing while a gap is open."""
    assert derive(escrow_module, 4, 4, gaps=1) == ("NEEDS_CLARIFICATION", 0)


def test_gaps_outrank_blockers(escrow_module):
    """'I could not read it' must never harden into 'it is disqualified'."""
    assert derive(escrow_module, 4, 4, blockers=1, gaps=1) == ("NEEDS_CLARIFICATION", 0)


def test_blockers_outrank_completion(escrow_module):
    assert derive(escrow_module, 4, 4, blockers=1) == ("REJECTED", 0)


def test_nonsensical_counts_do_not_pay(escrow_module):
    assert derive(escrow_module, 5, 4) == ("NEEDS_CLARIFICATION", 0)
    assert derive(escrow_module, 0, 0) == ("NEEDS_CLARIFICATION", 0)


# ---------------------------------------------------------------------------
# Model output parsing
# ---------------------------------------------------------------------------


def parse(escrow_module, payload, count=3):
    return escrow_module._parse_review_response(payload, count)


def test_clean_response_parses(escrow_module):
    out = parse(
        escrow_module,
        {"met": ["R1", "R2"], "unmet": ["R3"], "blockers": [], "gaps": [], "confidence": 88},
    )
    assert out == {"met_count": 2, "blocker_mask": 0, "gap_mask": 0, "confidence": 88}


@pytest.mark.parametrize(
    "payload",
    [
        "```json\n{\"met\": []}\n```",           # fenced markdown
        "not json at all",
        {"met": ["R1"], "unmet": ["R2", "R3"]},   # missing keys
        {"met": ["R1"], "unmet": ["R2", "R3"], "blockers": [], "gaps": [], "confidence": 88, "why": "x"},
        {"met": ["R1"], "unmet": ["R2", "R3"], "blockers": [], "gaps": [], "confidence": "high"},
        {"met": ["R1"], "unmet": ["R2", "R3"], "blockers": [], "gaps": [], "confidence": 140},
        {"met": "R1", "unmet": ["R2", "R3"], "blockers": [], "gaps": [], "confidence": 88},
        None,
    ],
)
def test_malformed_output_becomes_a_gap_not_an_exception(escrow_module, payload):
    """A model that returns garbage must never crash or reject — only stall."""
    out = parse(escrow_module, payload)
    assert out["gap_mask"] != 0
    assert out["blocker_mask"] == 0


def test_unknown_requirement_id_is_its_own_gap(escrow_module):
    out = parse(
        escrow_module,
        {"met": ["R1", "R9"], "unmet": ["R2", "R3"], "blockers": [], "gaps": [], "confidence": 88},
    )
    expected = 1 << escrow_module.GAP_KEYS.index("requirement_id_unknown")
    assert out["gap_mask"] == expected


@pytest.mark.parametrize(
    "met,unmet",
    [
        (["R1"], ["R2"]),                    # R3 never classified
        (["R1", "R1", "R2"], ["R3"]),        # duplicate in met
        (["R1", "R2"], ["R2", "R3"]),        # R2 in both lists
    ],
)
def test_incomplete_coverage_is_a_gap(escrow_module, met, unmet):
    out = parse(escrow_module, {"met": met, "unmet": unmet, "blockers": [], "gaps": [], "confidence": 90})
    expected = 1 << escrow_module.GAP_KEYS.index("requirement_coverage_incomplete")
    assert out["gap_mask"] == expected


def test_model_cannot_assert_a_code_decided_blocker(escrow_module):
    """`release_predates_grant` is arithmetic; the model has no standing on it."""
    out = parse(
        escrow_module,
        {
            "met": ["R1", "R2", "R3"],
            "unmet": [],
            "blockers": ["release_predates_grant"],
            "gaps": [],
            "confidence": 95,
        },
    )
    assert out["blocker_mask"] == 0
    assert out["gap_mask"] == 1 << escrow_module.GAP_KEYS.index("llm_output_unusable")


def test_model_blockers_within_scope_are_accepted(escrow_module):
    out = parse(
        escrow_module,
        {
            "met": [],
            "unmet": ["R1", "R2", "R3"],
            "blockers": ["unrelated_repository"],
            "gaps": [],
            "confidence": 91,
        },
    )
    assert out["blocker_mask"] == 1 << escrow_module.BLOCKER_KEYS.index("unrelated_repository")


# ---------------------------------------------------------------------------
# Masks and money
# ---------------------------------------------------------------------------


def test_mask_round_trip(escrow_module):
    keys = ["deliverable_unverifiable", "criteria_ambiguous"]
    mask = escrow_module._keys_to_mask(
        escrow_module.GAP_KEYS, escrow_module.LLM_ALLOWED_GAPS, keys, escrow_module.GAP_KEYS
    )
    assert sorted(escrow_module._mask_to_keys(mask, escrow_module.GAP_KEYS)) == sorted(keys)


def test_appeal_bond_takes_the_larger_of_share_and_floor(escrow_module):
    policy = {"appeal_bond_bps": 1000, "min_appeal_bond": 5_000}
    # 10% of 60000 is 6000, above the floor.
    assert escrow_module._required_appeal_bond(60_000, policy) == 6_000
    # 10% of 20000 is 2000, so the floor applies.
    assert escrow_module._required_appeal_bond(20_000, policy) == 5_000


def test_requirement_ids_are_one_indexed(escrow_module):
    assert escrow_module._requirement_ids(3) == ["R1", "R2", "R3"]
