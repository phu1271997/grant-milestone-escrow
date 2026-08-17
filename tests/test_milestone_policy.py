"""MilestonePolicy: rules that cannot move once a grant depends on them."""

import pytest

import genlayer_stub as glstub
from genlayer_stub import UserError
from conftest import DEFAULT_POLICY, SPONSOR, STRANGER


def publish(policy, sender=SPONSOR, **overrides):
    spec = dict(DEFAULT_POLICY)
    spec.update(overrides)
    return glstub.call(
        policy,
        "publish_policy",
        spec["policy_id"],
        spec["label"],
        spec["substantial_permille"],
        spec["partial_permille"],
        spec["substantial_payout_bps"],
        spec["partial_payout_bps"],
        spec["confidence_threshold"],
        spec["appeal_bond_bps"],
        spec["min_appeal_bond"],
        spec["max_reviews_per_milestone"],
        sender=sender,
    )


@pytest.fixture()
def policy(scenario):
    """The already-deployed registry, with `standard-v1` published."""
    return scenario.policy


def test_a_published_policy_reads_back_intact(policy):
    stored = glstub.view(policy, "get_policy", "standard-v1")
    assert stored["substantial_permille"] == "750"
    assert stored["partial_payout_bps"] == "5000"
    assert stored["confidence_threshold"] == "70"
    assert stored["publisher"] == SPONSOR


def test_a_policy_id_cannot_be_reused(policy):
    """This is the whole point: a live grant's rules cannot be rewritten."""
    with pytest.raises(UserError) as excinfo:
        publish(policy, substantial_permille=900)
    assert "POLICY_ALREADY_EXISTS" in str(excinfo.value)
    assert glstub.view(policy, "get_policy", "standard-v1")["substantial_permille"] == "750"


def test_only_the_publisher_may_add_policies(policy):
    with pytest.raises(UserError) as excinfo:
        publish(policy, policy_id="rogue-v1", sender=STRANGER)
    assert "NOT_PUBLISHER" in str(excinfo.value)


def test_unknown_policies_raise(policy):
    with pytest.raises(UserError) as excinfo:
        glstub.view(policy, "get_policy", "does-not-exist")
    assert "POLICY_NOT_FOUND" in str(excinfo.value)


def test_existence_probe_never_raises(policy):
    assert policy.policy_exists("standard-v1") is True
    assert policy.policy_exists("does-not-exist") is False
    assert policy.policy_exists("!! not even valid !!") is False


@pytest.mark.parametrize(
    "overrides,expected",
    [
        # 'Substantial' below 60% of the requirements would pay most of the
        # money for barely more than half the work.
        ({"substantial_permille": 550}, "INVALID_SUBSTANTIAL_BAND"),
        ({"substantial_permille": 1000}, "INVALID_SUBSTANTIAL_BAND"),
        # Bands must be strictly ordered.
        ({"partial_permille": 800}, "INVALID_PARTIAL_BAND"),
        ({"partial_permille": 0}, "INVALID_PARTIAL_BAND"),
        ({"partial_payout_bps": 8000}, "INVALID_PAYOUT_BANDS"),
        ({"substantial_payout_bps": 10000}, "INVALID_PAYOUT_BANDS"),
        # A jury allowed to be 20% sure is not a jury.
        ({"confidence_threshold": 20}, "INVALID_CONFIDENCE_THRESHOLD"),
        ({"confidence_threshold": 101}, "INVALID_CONFIDENCE_THRESHOLD"),
        # An appeal costing more than half the milestone is a bar, not a forum.
        ({"appeal_bond_bps": 6000}, "INVALID_APPEAL_BOND_BPS"),
        ({"appeal_bond_bps": 0}, "INVALID_APPEAL_BOND_BPS"),
        ({"min_appeal_bond": 0}, "INVALID_MIN_APPEAL_BOND"),
        ({"max_reviews_per_milestone": 0}, "INVALID_MAX_REVIEWS"),
        ({"max_reviews_per_milestone": 99}, "INVALID_MAX_REVIEWS"),
    ],
)
def test_unreasonable_policies_are_refused(policy, overrides, expected):
    overrides = dict(overrides)
    overrides["policy_id"] = "candidate-v1"
    with pytest.raises(UserError) as excinfo:
        publish(policy, **overrides)
    assert expected in str(excinfo.value)


@pytest.mark.parametrize("policy_id", ["ab", "x" * 65, "has spaces", "has/slash"])
def test_malformed_policy_ids_are_refused(policy, policy_id):
    with pytest.raises(UserError) as excinfo:
        publish(policy, policy_id=policy_id)
    assert "INVALID_POLICY_ID" in str(excinfo.value)


def test_policies_list_in_publication_order(policy):
    publish(policy, policy_id="strict-v1", confidence_threshold=90)
    publish(policy, policy_id="lenient-v1", confidence_threshold=55)
    listing = glstub.view(policy, "get_policies")
    assert listing["total"] == "3"
    assert [item["policy_id"] for item in listing["items"]] == [
        "standard-v1",
        "strict-v1",
        "lenient-v1",
    ]


def test_a_grant_is_judged_by_the_policy_it_pinned(scenario):
    """Publishing a stricter policy later leaves existing grants untouched."""
    scenario.publish_policy(policy_id="strict-v1", substantial_permille=990, partial_permille=980)

    grant_id = scenario.create_grant(policy_id="standard-v1", criteria_count=4)
    scenario.submit(grant_id)
    scenario.llm.reply = {
        "met": ["R1", "R2", "R3"],
        "unmet": ["R4"],
        "blockers": [],
        "gaps": [],
        "confidence": 88,
    }
    scenario.review(grant_id)

    # 750 permille: SUBSTANTIAL under standard-v1, INSUFFICIENT under strict-v1.
    assert scenario.milestone(grant_id)["settled_tier"] == "SUBSTANTIAL"
