"""The appeal forum: what a bond buys, and what it costs.

An appeal exists so that a "no" is not final. A bond exists so that an appeal is
not free. The interesting cases are the ones where those two pull against each
other.
"""

import pytest

import genlayer_stub as glstub
from genlayer_stub import UserError
from conftest import GRANTEE, SPONSOR, STRANGER


def answer(met_ids, total=3, confidence=90):
    all_ids = [f"R{i + 1}" for i in range(total)]
    return {
        "met": list(met_ids),
        "unmet": [rid for rid in all_ids if rid not in set(met_ids)],
        "blockers": [],
        "gaps": [],
        "confidence": confidence,
    }


@pytest.fixture()
def partial(scenario):
    """A milestone settled at PARTIAL: 30000 of 60000 paid, appeal still open."""
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.llm.reply = answer(["R1", "R2"])
    scenario.review(grant_id)
    assert scenario.milestone(grant_id)["settled_tier"] == "PARTIAL"
    return grant_id


# ---------------------------------------------------------------------------
# Quoting the bond
# ---------------------------------------------------------------------------


def test_the_bond_is_quoted_before_any_wallet_prompt(scenario, partial):
    quote = scenario.appeal_quote(partial)
    assert quote["required_bond"] == "6000"  # 10% of the 60000 allocation
    assert quote["appealable"] is True
    assert quote["current_tier"] == "PARTIAL"


def test_a_complete_milestone_has_nothing_to_appeal(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)
    assert scenario.appeal_quote(grant_id)["appealable"] is False


def test_the_bond_must_match_the_quote_exactly(scenario, partial):
    """Not a minimum: overpaying would leave change with no rule to return it."""
    with pytest.raises(UserError) as excinfo:
        scenario.appeal(partial, 0, "The auth module ships in this very release.", bond=5_999)
    assert "INVALID_APPEAL_BOND" in str(excinfo.value)

    with pytest.raises(UserError):
        scenario.appeal(partial, 0, "The auth module ships in this very release.", bond=6_001)


# ---------------------------------------------------------------------------
# Standing
# ---------------------------------------------------------------------------


def test_only_the_grantee_may_appeal(scenario, partial):
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.escrow, "file_appeal", partial, 0,
            "This review missed the shipped auth module entirely.", "",
            sender=STRANGER, value=6_000,
        )
    assert "NOT_GRANTEE" in str(excinfo.value)


def test_a_complete_milestone_cannot_be_appealed(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)
    with pytest.raises(UserError) as excinfo:
        scenario.appeal(grant_id, 0, "I would like even more than everything.", bond=6_000)
    assert "MILESTONE_NOT_APPEALABLE" in str(excinfo.value)


def test_a_rebuttal_must_actually_say_something(scenario, partial):
    with pytest.raises(UserError) as excinfo:
        scenario.appeal(partial, 0, "wrong", bond=6_000)
    assert "INVALID_REBUTTAL" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_a_successful_appeal_pays_the_difference_and_returns_the_bond(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2", "R3"])
    scenario.appeal(partial, 0, "R3 is covered by the tests added in this release.", bond=6_000)

    milestone = scenario.milestone(partial)
    assert milestone["settled_tier"] == "COMPLETE"
    assert milestone["paid_amount"] == "60000"
    assert milestone["state"] == "3"
    assert milestone["appeal_filed"] is True
    # 30000 initial, minus the 6000 bond, plus 30000 difference and the bond back.
    assert scenario.world.balance_of(GRANTEE) == 60_000


def test_a_failed_appeal_forfeits_the_bond_to_the_sponsor(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2"])  # unchanged reading
    scenario.appeal(partial, 0, "I still believe R3 was delivered on time.", bond=6_000)

    milestone = scenario.milestone(partial)
    grant = scenario.grant(partial)
    assert milestone["settled_tier"] == "PARTIAL"
    assert milestone["paid_amount"] == "30000"
    assert milestone["state"] == "3"
    assert scenario.world.balance_of(GRANTEE) == 24_000  # 30000 paid, 6000 forfeited
    # The bond returns to the grant balance rather than becoming anyone's profit.
    assert grant["escrowed"] == "76000"


def test_a_downgrade_on_appeal_never_claws_money_back(scenario, partial):
    """An appeal can only raise the tier. Risking a clawback would kill the forum."""
    scenario.llm.reply = answer(["R1"])  # would be INSUFFICIENT on its own
    scenario.appeal(partial, 0, "Reconsider the scope of the first requirement.", bond=6_000)

    milestone = scenario.milestone(partial)
    assert milestone["settled_tier"] == "PARTIAL"
    assert milestone["paid_amount"] == "30000"
    assert scenario.world.balance_of(GRANTEE) == 24_000


def test_an_unreadable_appeal_refunds_the_bond_and_stays_open(scenario, partial):
    """The builder does not pay for the network being down."""
    scenario.page_offline = True
    scenario.appeal(partial, 0, "The demo was live when I submitted this milestone.", bond=6_000)

    milestone = scenario.milestone(partial)
    assert milestone["appeal_filed"] is False
    assert milestone["state"] == "2"  # still SETTLED, still appealable
    assert scenario.world.balance_of(GRANTEE) == 30_000  # bond returned in full
    assert scenario.latest_review(partial)["tier"] == "NEEDS_CLARIFICATION"

    # And the forum is genuinely still open.
    scenario.page_offline = False
    scenario.llm.reply = answer(["R1", "R2", "R3"])
    scenario.appeal(partial, 0, "The demo is back up; please look again.", bond=6_000)
    assert scenario.milestone(partial)["settled_tier"] == "COMPLETE"


def test_an_appeal_may_be_filed_only_once(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2"])
    scenario.appeal(partial, 0, "Please reconsider the second requirement carefully.", bond=6_000)
    with pytest.raises(UserError) as excinfo:
        scenario.appeal(partial, 0, "Please reconsider it once more, with feeling.", bond=6_000)
    assert "MILESTONE_NOT_APPEALABLE" in str(excinfo.value)


def test_the_rebuttal_reaches_the_second_jury(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2", "R3"])
    rebuttal = "R3 is implemented in src/auth/session.ts and covered by tests."
    scenario.appeal(partial, 0, rebuttal, bond=6_000)

    appeal_prompt = scenario.world.prompt_log[-1]
    assert rebuttal in appeal_prompt
    assert "PARTIAL" in appeal_prompt  # the second jury is told what the first said


def test_extra_evidence_replaces_the_page_for_the_second_review(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2", "R3"])
    scenario.appeal(
        partial, 0,
        "Here is the deployed staging environment showing the auth flow.",
        bond=6_000,
        url="https://staging.example/auth",
    )
    assert scenario.world.render_log[-1] == "https://staging.example/auth"
    assert scenario.latest_review(partial)["evidence_url"] == "https://staging.example/auth"


def test_review_history_records_both_rounds(scenario, partial):
    scenario.llm.reply = answer(["R1", "R2", "R3"])
    scenario.appeal(partial, 0, "R3 landed in the same release as R1 and R2.", bond=6_000)

    history = glstub.view(scenario.escrow, "get_reviews", partial, 0, 0, 50)
    assert history["total"] == "2"
    assert [item["kind"] for item in history["items"]] == ["0", "1"]
    assert [item["tier"] for item in history["items"]] == ["PARTIAL", "COMPLETE"]
