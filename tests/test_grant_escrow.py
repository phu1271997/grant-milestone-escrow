"""Lifecycle, money and edge cases for GrantEscrow."""

import json

import pytest

import genlayer_stub as glstub
from genlayer_stub import UserError
from conftest import GRANTEE, SPONSOR, STRANGER


def code(excinfo) -> str:
    """The `[EXPECTED] X` marker a contract raised."""
    return str(excinfo.value)


def answer(met_ids, total=3, confidence=90):
    all_ids = [f"R{i + 1}" for i in range(total)]
    return {
        "met": list(met_ids),
        "unmet": [rid for rid in all_ids if rid not in set(met_ids)],
        "blockers": [],
        "gaps": [],
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Grant creation
# ---------------------------------------------------------------------------


def test_deposit_is_fully_allocated_across_milestones(scenario):
    grant_id = scenario.create_grant(allocations=(60_000, 40_000))
    grant = scenario.grant(grant_id)

    assert grant["deposit"] == "100000"
    assert grant["escrowed"] == "100000"
    assert grant["released"] == "0"
    assert grant["milestone_count"] == "2"
    assert grant["sponsor"] == SPONSOR
    assert grant["grantee"] == GRANTEE
    assert scenario.world.balance_of(scenario.escrow.__gl_address__) == 100_000


def test_criteria_are_frozen_at_creation(scenario):
    grant_id = scenario.create_grant(criteria_count=4)
    milestone = scenario.milestone(grant_id)
    assert len(milestone["criteria"]) == 4
    assert milestone["requirement_ids"] == ["R1", "R2", "R3", "R4"]


def test_deposit_must_equal_the_sum_of_allocations(scenario):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "50000", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, "acme/widget", "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=60_000,
        )
    assert "ALLOCATION_DEPOSIT_MISMATCH" in code(excinfo)


def test_zero_deposit_is_refused(scenario):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "1", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, "acme/widget", "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=0,
        )
    assert "ZERO_DEPOSIT" in code(excinfo)


def test_zero_allocation_milestone_is_refused(scenario):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "0", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, "acme/widget", "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=1,
        )
    assert "ZERO_ALLOCATION" in code(excinfo)


def test_sponsor_cannot_fund_themselves(scenario):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "10", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", SPONSOR, "acme/widget", "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=10,
        )
    assert "SPONSOR_IS_GRANTEE" in code(excinfo)


def test_duplicate_criteria_are_refused(scenario):
    """A repeated requirement would silently move the tier bands."""
    milestones = json.dumps(
        [{
            "title": "M1",
            "allocation": "10",
            "criteria": ["Ship the auth module.", "ship the AUTH module."],
        }]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, "acme/widget", "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=10,
        )
    assert "DUPLICATE_CRITERION" in code(excinfo)


def test_unknown_policy_is_refused_before_taking_custody(scenario):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "10", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, "acme/widget", "Grant", "no-such-policy",
            milestones, 90, sender=SPONSOR, value=10,
        )
    assert "POLICY_NOT_FOUND" in code(excinfo)


@pytest.mark.parametrize("repo", ["", "acme", "acme/widget/extra", "acme/../etc", "acme/wid get"])
def test_malformed_repositories_are_refused(scenario, repo):
    milestones = json.dumps(
        [{"title": "M1", "allocation": "10", "criteria": ["Ship the thing properly.", "Test it."]}]
    )
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "create_grant", GRANTEE, repo, "Grant", "standard-v1",
            milestones, 90, sender=SPONSOR, value=10,
        )
    assert "INVALID_REPO" in code(excinfo)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def test_only_the_grantee_may_submit(scenario):
    grant_id = scenario.create_grant()
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "submit_milestone", grant_id, 0, "v0.2.0",
            "https://demo.example/app", sender=STRANGER,
        )
    assert "NOT_GRANTEE" in code(excinfo)


def test_resubmitting_before_review_replaces_the_evidence(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id, tag="v0.1.0")
    scenario.submit(grant_id, tag="v0.2.0", url="https://demo.example/v2")
    milestone = scenario.milestone(grant_id)
    assert milestone["release_tag"] == "v0.2.0"
    assert milestone["evidence_url"] == "https://demo.example/v2"


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.example/app",       # not HTTPS
        "https://localhost/app",
        "https://127.0.0.1/app",
        "https://user:pw@demo.example/",
        "https://demo.example:8443/app",
    ],
)
def test_unreachable_or_private_evidence_urls_are_refused(scenario, url):
    grant_id = scenario.create_grant()
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "submit_milestone", grant_id, 0, "v0.2.0", url, sender=GRANTEE
        )
    assert "INVALID_EVIDENCE_URL" in code(excinfo)


def test_review_requires_a_submission(scenario):
    grant_id = scenario.create_grant()
    with pytest.raises(UserError) as excinfo:
        scenario.review(grant_id)
    assert "MILESTONE_NOT_SUBMITTED" in code(excinfo)


# ---------------------------------------------------------------------------
# Settlement and money
# ---------------------------------------------------------------------------


def test_complete_pays_the_whole_allocation_and_is_terminal(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)

    milestone = scenario.milestone(grant_id)
    grant = scenario.grant(grant_id)
    assert milestone["settled_tier"] == "COMPLETE"
    assert milestone["paid_amount"] == "60000"
    assert milestone["state"] == "3"  # FINAL — nothing left to argue about
    assert grant["escrowed"] == "40000"
    assert grant["released"] == "60000"
    assert scenario.world.balance_of(GRANTEE) == 60_000


def test_partial_pays_the_band_and_stays_appealable(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.llm.reply = answer(["R1", "R2"])  # 2 of 3 == 666 permille == PARTIAL
    scenario.review(grant_id)

    milestone = scenario.milestone(grant_id)
    assert milestone["settled_tier"] == "PARTIAL"
    assert milestone["paid_amount"] == "30000"  # 50% of 60000
    assert milestone["state"] == "2"  # SETTLED — still open to appeal
    assert scenario.world.balance_of(GRANTEE) == 30_000


def test_a_settled_milestone_cannot_be_reviewed_again(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)
    with pytest.raises(UserError) as excinfo:
        scenario.review(grant_id)
    assert "MILESTONE_NOT_SUBMITTED" in code(excinfo)
    assert scenario.world.balance_of(GRANTEE) == 60_000  # not paid twice


def test_anyone_may_convene_the_jury(scenario):
    """The caller has no influence on the outcome, so the call is open."""
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id, sender=STRANGER)
    assert scenario.milestone(grant_id)["settled_tier"] == "COMPLETE"


def test_milestones_settle_independently(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id, index=0)
    scenario.review(grant_id, index=0)
    scenario.submit(grant_id, index=1)
    scenario.llm.reply = answer(["R1", "R2"])
    scenario.review(grant_id, index=1)

    grant = scenario.grant(grant_id)
    assert grant["released"] == "80000"  # 60000 + 50% of 40000
    assert grant["escrowed"] == "20000"
    assert grant["settled_count"] == "2"


# ---------------------------------------------------------------------------
# Clarification path
# ---------------------------------------------------------------------------


def test_unreadable_evidence_page_stalls_instead_of_rejecting(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.page_offline = True
    scenario.review(grant_id)

    milestone = scenario.milestone(grant_id)
    review = scenario.latest_review(grant_id)
    assert review["tier"] == "NEEDS_CLARIFICATION"
    assert "evidence_page_unreachable" in review["gaps"]
    assert milestone["state"] == "0"  # back to OPEN for another attempt
    assert milestone["paid_amount"] == "0"
    assert scenario.world.balance_of(GRANTEE) == 0


def test_low_confidence_escalates_rather_than_guessing(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.llm.reply = answer(["R1", "R2", "R3"], confidence=55)  # policy floor is 70
    scenario.review(grant_id)

    review = scenario.latest_review(grant_id)
    assert review["tier"] == "NEEDS_CLARIFICATION"
    assert "confidence_below_policy_floor" in review["gaps"]


def test_a_stalled_milestone_can_be_resubmitted_and_settled(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.page_offline = True
    scenario.review(grant_id)

    scenario.page_offline = False
    scenario.submit(grant_id, tag="v0.2.1")
    scenario.review(grant_id)

    milestone = scenario.milestone(grant_id)
    assert milestone["settled_tier"] == "COMPLETE"
    assert milestone["review_count"] == "2"


def test_review_attempts_are_capped_by_policy(scenario):
    """Otherwise a stalled milestone could be re-rolled until it paid out."""
    scenario.publish_policy(policy_id="tight-v1", max_reviews_per_milestone=2)
    grant_id = scenario.create_grant(policy_id="tight-v1")
    scenario.submit(grant_id)
    scenario.page_offline = True

    scenario.review(grant_id)
    scenario.submit(grant_id)
    scenario.review(grant_id)
    scenario.submit(grant_id)

    with pytest.raises(UserError) as excinfo:
        scenario.review(grant_id)
    assert "REVIEW_LIMIT_REACHED" in code(excinfo)


# ---------------------------------------------------------------------------
# Evidence failures decided in code
# ---------------------------------------------------------------------------


def test_a_moved_tag_is_rejected(scenario):
    """A commit dated after its own release announcement means the tag moved."""
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    from conftest import _iso_offset

    scenario.github.commit = dict(
        scenario.github.commit, commit={"committer": {"date": _iso_offset(600)}}
    )
    scenario.review(grant_id)

    review = scenario.latest_review(grant_id)
    assert review["tier"] == "REJECTED"
    assert "source_commit_conflict" in review["blockers"]


def test_a_tag_pointing_outside_the_repository_is_rejected(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.github.offline.add("commit")
    scenario.review(grant_id)

    review = scenario.latest_review(grant_id)
    assert review["tier"] == "REJECTED"
    assert "commit_not_in_repository" in review["blockers"]


def test_an_unreachable_github_endpoint_stalls(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.github.offline.add("ref")
    scenario.review(grant_id)

    review = scenario.latest_review(grant_id)
    assert review["tier"] == "NEEDS_CLARIFICATION"
    assert "release_source_unreachable" in review["gaps"]


def test_a_draft_release_is_not_evidence(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.github.release = dict(scenario.github.release, draft=True)
    scenario.review(grant_id)
    assert scenario.latest_review(grant_id)["tier"] == "NEEDS_CLARIFICATION"


def test_annotated_tags_are_dereferenced(scenario):
    """An annotated tag points at a tag object, which points at the commit."""
    from conftest import COMMIT_SHA

    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.github.ref = {"object": {"sha": "cc" + "2" * 38, "type": "tag"}}
    scenario.github.annotated = {"object": {"sha": COMMIT_SHA, "type": "commit"}}

    scenario.review(grant_id)
    review = scenario.latest_review(grant_id)
    assert review["tier"] == "COMPLETE"
    assert review["commit_sha"] == COMMIT_SHA


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------


def test_only_the_sponsor_may_close(scenario):
    grant_id = scenario.create_grant()
    with pytest.raises(UserError) as excinfo:
        glstub.call(scenario.escrow, "close_grant", grant_id, sender=GRANTEE)
    assert "NOT_SPONSOR" in code(excinfo)


def test_closing_is_blocked_while_milestones_are_live(scenario):
    grant_id = scenario.create_grant()
    with pytest.raises(UserError) as excinfo:
        glstub.call(scenario.escrow, "close_grant", grant_id, sender=SPONSOR)
    assert "GRANT_STILL_OPEN" in code(excinfo)


def test_closing_returns_the_unspent_remainder(scenario):
    grant_id = scenario.create_grant()
    for index in (0, 1):
        scenario.submit(grant_id, index=index)
        scenario.llm.reply = answer(["R1", "R2"])  # PARTIAL on both
        scenario.review(grant_id, index=index)

    refund = glstub.call(scenario.escrow, "close_grant", grant_id, sender=SPONSOR)

    assert int(refund) == 50_000  # half of each allocation went unpaid
    # Net position: deposited 100000, got 50000 back, so 50000 actually spent.
    assert scenario.world.balance_of(SPONSOR) == -50_000
    assert scenario.grant(grant_id)["status"] == "1"
    assert scenario.world.balance_of(scenario.escrow.__gl_address__) == 0


def test_a_closed_grant_accepts_nothing_further(scenario):
    grant_id = scenario.create_grant()
    for index in (0, 1):
        scenario.submit(grant_id, index=index)
        scenario.review(grant_id, index=index)
    glstub.call(scenario.escrow, "close_grant", grant_id, sender=SPONSOR)

    with pytest.raises(UserError) as excinfo:
        scenario.submit(grant_id)
    assert "GRANT_NOT_ACTIVE" in code(excinfo)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def test_taxonomy_view_lets_a_reader_decode_any_mask(scenario):
    taxonomy = glstub.view(scenario.escrow, "get_taxonomy")
    assert "release_predates_grant" in taxonomy["code_blockers"]
    assert "unrelated_repository" in taxonomy["llm_blockers"]
    assert set(taxonomy["code_blockers"]) | set(taxonomy["llm_blockers"]) == set(taxonomy["blockers"])
    assert "NEEDS_CLARIFICATION" in taxonomy["tiers"]


def test_bindings_view_exposes_the_companion_contracts(scenario):
    bindings = glstub.view(scenario.escrow, "get_bindings")
    assert bindings["policy_contract"] == scenario.policy.__gl_address__
    assert bindings["reputation_contract"] == scenario.reputation.__gl_address__


def test_every_integer_leaves_as_a_string(scenario):
    """JavaScript would silently round a large allocation read as a number."""
    grant_id = scenario.create_grant()
    grant = scenario.grant(grant_id)
    for field in ("deposit", "escrowed", "released", "milestone_count"):
        assert isinstance(grant[field], str)


def test_unknown_identifiers_raise_rather_than_return_empty(scenario):
    with pytest.raises(UserError):
        glstub.view(scenario.escrow, "get_grant", "999")
    with pytest.raises(UserError):
        glstub.view(scenario.escrow, "get_review", "999")
