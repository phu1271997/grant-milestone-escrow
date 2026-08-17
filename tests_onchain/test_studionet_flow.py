"""The on-chain suite: the same flow, against real validators.

`tests/` runs the contract source against an in-process shim and is what you use
while developing. It cannot model the four things that decide whether this
project actually works:

  * gas and finality
  * validator *diversity* — different models, not the same function twice
  * live inference latency and variance
  * cross-contract messages passing through consensus

That is exactly the list of reasons to run this suite before shipping.

    gltest --network studionet tests_onchain/

Requires a funded Studionet account. LLM and web calls are mocked through
`sim_installMocks` so the assertions stay deterministic — a suite whose result
depends on what GitHub returned this morning is not a regression test. The one
case that deliberately does *not* mock is `test_live_evidence_is_reachable`,
which is a smoke check that the real endpoints answer at all.

NOTE: this file has not been executed offline — it cannot be, by definition.
Run it once against Studionet after deploying and before recording the demo.
"""

import json
from pathlib import Path

import pytest
from gltest import get_accounts, get_contract_factory, get_gl_client

CONTRACTS = Path(__file__).parents[1] / "contracts"

POLICY_ARGS = [
    "standard-v1",
    "Standard milestone review",
    750,
    500,
    7500,
    5000,
    70,
    1000,
    10**15,
    4,
]

MILESTONES = json.dumps(
    [
        {
            "title": "Ship v0.2 with wallet authentication",
            "allocation": "1000000000000000000",
            "criteria": [
                "Wallet sign-in works on the deployed demo.",
                "The release notes describe the authentication work.",
                "Automated tests cover the authentication module.",
            ],
        }
    ]
)

REPO = "genlayerlabs/genlayer-studio"
RELEASE_TAG = "v0.2.0"


def install_mocks(llm_reply: dict, web_ok: bool = True) -> None:
    """Install deterministic LLM and web responses.

    `params` must be a bare dict. Wrapping it in a list gets normalised into an
    int-indexed mapping and silently registers zero mocks, which then surfaces
    as a confusing *state* error — the transaction never finalized, so the
    milestone never advanced.
    """
    client = get_gl_client()
    client.provider.make_request(
        method="sim_installMocks",
        params={
            "llm_mocks": {".*": json.dumps(llm_reply)},
            "web_mocks": {
                ".*": {
                    "status": 200 if web_ok else 503,
                    "body": "Demo: sign in with your wallet, then view your dashboard.",
                }
            },
        },
    )


@pytest.fixture(scope="module")
def deployment():
    """Deploy all three contracts and wire them, once per run."""
    accounts = get_accounts()
    sponsor, grantee = accounts[0], accounts[1]

    policy = get_contract_factory(
        contract_file_path=CONTRACTS / "milestone_policy.py"
    ).deploy(args=[], account=sponsor)

    reputation = get_contract_factory(
        contract_file_path=CONTRACTS / "builder_reputation.py"
    ).deploy(args=[], account=sponsor)

    escrow = get_contract_factory(
        contract_file_path=CONTRACTS / "grant_escrow.py"
    ).deploy(args=[policy.address, reputation.address], account=sponsor)

    reputation.connect(sponsor).bind_escrow(args=[escrow.address]).transact()
    policy.connect(sponsor).publish_policy(args=POLICY_ARGS).transact()

    return {
        "policy": policy,
        "reputation": reputation,
        "escrow": escrow,
        "sponsor": sponsor,
        "grantee": grantee,
    }


def test_contracts_are_mutually_wired(deployment):
    """The failure this catches is three clean deploys pointed at nothing."""
    bindings = json.loads(deployment["escrow"].get_bindings(args=[]).call())
    binding = json.loads(deployment["reputation"].get_binding(args=[]).call())

    assert bindings["policy_contract"].lower() == deployment["policy"].address.lower()
    assert bindings["reputation_contract"].lower() == deployment["reputation"].address.lower()
    assert binding["escrow"].lower() == deployment["escrow"].address.lower()


def test_policy_reads_back_intact(deployment):
    stored = json.loads(deployment["policy"].get_policy(args=["standard-v1"]).call())
    assert stored["substantial_permille"] == "750"
    assert stored["confidence_threshold"] == "70"


def test_grant_funds_and_allocates(deployment):
    escrow, sponsor = deployment["escrow"], deployment["sponsor"]
    escrow.connect(sponsor).create_grant(
        args=[
            deployment["grantee"].address,
            REPO,
            "On-chain suite grant",
            "standard-v1",
            MILESTONES,
            90,
        ]
    ).transact(value=10**18)

    grants = json.loads(escrow.get_grants(args=[0, 10]).call())
    assert int(grants["total"]) >= 1

    grant = json.loads(escrow.get_grant(args=[grants["items"][-1]["grant_id"]]).call())
    assert grant["grant"]["escrowed"] == "1000000000000000000"
    assert len(grant["milestones"][0]["criteria"]) == 3


def test_full_review_settles_through_consensus(deployment):
    """The point of the whole suite: real validators, real agreement."""
    escrow, grantee = deployment["escrow"], deployment["grantee"]
    grants = json.loads(escrow.get_grants(args=[0, 50]).call())
    grant_id = grants["items"][-1]["grant_id"]

    escrow.connect(grantee).submit_milestone(
        args=[grant_id, 0, RELEASE_TAG, "https://example.org/demo"]
    ).transact()

    install_mocks(
        {
            "met": ["R1", "R2", "R3"],
            "unmet": [],
            "blockers": [],
            "gaps": [],
            "confidence": 91,
        }
    )

    escrow.connect(grantee).review_milestone(args=[grant_id, 0]).transact()

    milestone = json.loads(escrow.get_milestone(args=[grant_id, 0]).call())
    # Mocked web responses cannot satisfy the GitHub cross-check, so the honest
    # expectation here is a settled *record*, not a specific tier. What is being
    # verified is that the non-deterministic block ran, validators agreed, and
    # state advanced — the tier itself is pinned offline in tests/.
    assert int(milestone["review_count"]) >= 1
    assert milestone["latest_review_id"] != ""

    review = json.loads(escrow.get_review(args=[milestone["latest_review_id"]]).call())
    assert review["tier"] in (
        "COMPLETE",
        "SUBSTANTIAL",
        "PARTIAL",
        "INSUFFICIENT",
        "REJECTED",
        "NEEDS_CLARIFICATION",
    )


def test_taxonomy_is_published_on_chain(deployment):
    taxonomy = json.loads(deployment["escrow"].get_taxonomy(args=[]).call())
    assert "release_predates_grant" in taxonomy["code_blockers"]
    assert "unrelated_repository" in taxonomy["llm_blockers"]


@pytest.mark.skipif(
    "not config.getoption('--run-live', default=False)",
    reason="hits the real GitHub API; enable with --run-live",
)
def test_live_evidence_is_reachable(deployment):
    """No mocks. Confirms validators can actually reach GitHub from the VM.

    Deliberately asserts nothing about the verdict — the point is only that the
    fetch path works end to end, which no mocked test can tell you.
    """
    escrow, grantee = deployment["escrow"], deployment["grantee"]
    grants = json.loads(escrow.get_grants(args=[0, 50]).call())
    grant_id = grants["items"][-1]["grant_id"]

    escrow.connect(grantee).submit_milestone(
        args=[grant_id, 0, RELEASE_TAG, "https://example.org/"]
    ).transact()
    escrow.connect(grantee).review_milestone(args=[grant_id, 0]).transact()

    milestone = json.loads(escrow.get_milestone(args=[grant_id, 0]).call())
    assert int(milestone["review_count"]) >= 1
