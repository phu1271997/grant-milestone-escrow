"""BuilderReputation: a ledger only the escrow can write."""

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


# ---------------------------------------------------------------------------
# The trust boundary
# ---------------------------------------------------------------------------


def test_binding_is_visible_to_anyone(scenario):
    binding = glstub.view(scenario.reputation, "get_binding")
    assert binding["bound"] is True
    assert binding["escrow"] == scenario.escrow.__gl_address__


def test_binding_happens_once_and_never_again(scenario):
    with pytest.raises(UserError) as excinfo:
        glstub.call(scenario.reputation, "bind_escrow", "0x" + "de" * 20, sender=SPONSOR)
    assert "ESCROW_ALREADY_BOUND" in str(excinfo.value)


def test_outsiders_cannot_write_records(scenario):
    """A reputation anyone can write is worth nothing."""
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.reputation, "record_settlement", GRANTEE, "COMPLETE", 1_000_000,
            sender=STRANGER,
        )
    assert "NOT_AUTHORIZED_WRITER" in str(excinfo.value)


def test_even_the_deployer_cannot_write_records(scenario):
    """Binding is an additive privilege, not a standing one."""
    with pytest.raises(UserError) as excinfo:
        glstub.call(
            scenario.reputation, "record_settlement", GRANTEE, "COMPLETE", 1_000_000,
            sender=SPONSOR,
        )
    assert "NOT_AUTHORIZED_WRITER" in str(excinfo.value)


def test_an_unbound_ledger_accepts_nothing(world, modules):
    reputation = glstub.deploy(modules["reputation"], SPONSOR)
    with pytest.raises(UserError) as excinfo:
        glstub.call(reputation, "record_clarification", GRANTEE, sender=SPONSOR)
    assert "ESCROW_NOT_BOUND" in str(excinfo.value)


def test_only_the_deployer_may_bind(world, modules):
    reputation = glstub.deploy(modules["reputation"], SPONSOR)
    with pytest.raises(UserError) as excinfo:
        glstub.call(reputation, "bind_escrow", "0x" + "de" * 20, sender=STRANGER)
    assert "NOT_DEPLOYER" in str(excinfo.value)


# ---------------------------------------------------------------------------
# What the escrow records
# ---------------------------------------------------------------------------


def test_an_unknown_builder_reads_as_zeroed_rather_than_missing(scenario):
    record = scenario.reputation_of(STRANGER)
    assert record["known"] is False
    assert record["settlements"] == "0"


def test_a_settlement_is_recorded_through_the_cross_contract_call(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)

    record = scenario.reputation_of(GRANTEE)
    assert record["known"] is True
    assert record["settlements"] == "1"
    assert record["complete"] == "1"
    assert record["total_paid"] == "60000"


def test_clarifications_are_counted_apart_from_rejections(scenario):
    """Needing a clearer submission is a process signal, not a quality verdict."""
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.page_offline = True
    scenario.review(grant_id)

    record = scenario.reputation_of(GRANTEE)
    assert record["clarifications"] == "1"
    assert record["rejected"] == "0"
    assert record["settlements"] == "0"


def test_tiers_are_tallied_separately(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id, index=0)
    scenario.review(grant_id, index=0)                      # COMPLETE
    scenario.submit(grant_id, index=1)
    scenario.llm.reply = answer(["R1", "R2"])               # PARTIAL
    scenario.review(grant_id, index=1)

    record = scenario.reputation_of(GRANTEE)
    assert record["complete"] == "1"
    assert record["partial"] == "1"
    assert record["settlements"] == "2"
    assert record["total_paid"] == "80000"


def test_an_upheld_appeal_is_recorded_as_such(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.llm.reply = answer(["R1", "R2"])
    scenario.review(grant_id)

    scenario.llm.reply = answer(["R1", "R2", "R3"])
    scenario.appeal(grant_id, 0, "R3 shipped in the same release as the rest.", bond=6_000)

    record = scenario.reputation_of(GRANTEE)
    assert record["appeals_filed"] == "1"
    assert record["appeals_upheld"] == "1"
    assert record["total_paid"] == "60000"  # 30000 initial plus 30000 difference


def test_a_failed_appeal_is_recorded_without_an_upheld(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.llm.reply = answer(["R1", "R2"])
    scenario.review(grant_id)
    scenario.appeal(grant_id, 0, "I maintain that everything was delivered.", bond=6_000)

    record = scenario.reputation_of(GRANTEE)
    assert record["appeals_filed"] == "1"
    assert record["appeals_upheld"] == "0"


def test_builders_paginate_in_first_seen_order(scenario):
    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)

    page = glstub.view(scenario.reputation, "get_builders", 0, 50)
    assert page["total"] == "1"
    assert page["items"][0]["builder"] == GRANTEE
    assert page["next_cursor"] is None


def test_a_broken_ledger_never_blocks_a_payout(scenario, monkeypatch):
    """Bookkeeping must not be able to strand money consensus already released."""
    def explode(*args, **kwargs):
        raise UserError("[EXPECTED] LEDGER_BROKEN")

    monkeypatch.setattr(scenario.reputation, "record_settlement", explode)

    grant_id = scenario.create_grant()
    scenario.submit(grant_id)
    scenario.review(grant_id)

    assert scenario.milestone(grant_id)["settled_tier"] == "COMPLETE"
    assert scenario.world.balance_of(GRANTEE) == 60_000
    assert scenario.reputation_of(GRANTEE)["settlements"] == "0"
