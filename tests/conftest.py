"""Shared fixtures: a three-contract deployment and a fake GitHub."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import genlayer_stub as glstub  # noqa: E402

CONTRACTS = Path(__file__).parents[1] / "contracts"

SPONSOR = "0x" + "a1" * 20
GRANTEE = "0x" + "b2" * 20
STRANGER = "0x" + "c3" * 20

COMMIT_SHA = "9f" + "0" * 38


def _iso_offset(minutes: int) -> str:
    """A UTC timestamp `minutes` away from now, in GitHub's `...Z` format.

    Evidence timestamps have to be generated relative to the clock rather than
    hardcoded: the contract blocks any release published before its grant was
    created, and a grant created during the test run is always "now".
    """
    import datetime

    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")

DEFAULT_POLICY = {
    "policy_id": "standard-v1",
    "label": "Standard milestone review",
    "substantial_permille": 750,
    "partial_permille": 500,
    "substantial_payout_bps": 7500,
    "partial_payout_bps": 5000,
    "confidence_threshold": 70,
    "appeal_bond_bps": 1000,
    "min_appeal_bond": 1_000,
    "max_reviews_per_milestone": 4,
}


@pytest.fixture()
def world():
    """Fresh execution world per test — no state leaks between cases."""
    return glstub.reset_world()


@pytest.fixture()
def modules(world):
    """Load the three contract sources against the shim."""
    return {
        "policy": glstub.load_contract(CONTRACTS / "milestone_policy.py", "c_policy"),
        "reputation": glstub.load_contract(CONTRACTS / "builder_reputation.py", "c_reputation"),
        "escrow": glstub.load_contract(CONTRACTS / "grant_escrow.py", "c_escrow"),
    }


class GitHubFake:
    """A scriptable stand-in for the three GitHub endpoints the contract reads.

    Kept mutable so a test can move a tag, backdate a release, or take one
    endpoint offline and watch the taxonomy react.
    """

    def __init__(self):
        self.release = {
            "draft": False,
            "prerelease": False,
            "published_at": _iso_offset(60),
            "body": "v0.2 adds wallet authentication, a public demo, and auth module tests.",
        }
        self.ref = {"object": {"sha": COMMIT_SHA, "type": "commit"}}
        self.annotated = None
        self.commit = {"sha": COMMIT_SHA, "commit": {"committer": {"date": _iso_offset(30)}}}
        self.offline = set()

    def handle(self, url, headers):
        if "/releases/tags/" in url:
            return self._reply("release", self.release)
        if "/git/ref/tags/" in url:
            return self._reply("ref", self.ref)
        if "/git/tags/" in url:
            return self._reply("annotated", self.annotated)
        if "/commits/" in url:
            return self._reply("commit", self.commit)
        return glstub.Response(404, b"{}")

    def _reply(self, name, payload):
        if name in self.offline or payload is None:
            return glstub.Response(404, b"{}")
        return glstub.json_response(payload)


class LLMFake:
    """A scriptable model. `reply` may be a dict, a raw string, or a callable."""

    def __init__(self, reply=None):
        self.reply = reply if reply is not None else {
            "met": ["R1", "R2", "R3"],
            "unmet": [],
            "blockers": [],
            "gaps": [],
            "confidence": 92,
        }
        self.calls = 0

    def handle(self, prompt, response_format):
        self.calls += 1
        reply = self.reply(prompt) if callable(self.reply) else self.reply
        if isinstance(reply, str):
            return reply
        return json.loads(json.dumps(reply))


class Scenario:
    """A deployed system plus the knobs a test needs to steer it."""

    def __init__(self, world, modules):
        self.world = world
        self.github = GitHubFake()
        self.llm = LLMFake()
        self.page_text = "Demo: sign in with your wallet, then view your dashboard."
        self.page_offline = False

        world.http_handler = self.github.handle
        world.prompt_handler = self.llm.handle
        world.render_handler = self._render

        self.policy = glstub.deploy(modules["policy"], SPONSOR)
        self.reputation = glstub.deploy(modules["reputation"], SPONSOR)
        self.escrow = glstub.deploy(
            modules["escrow"],
            SPONSOR,
            self.policy.__gl_address__,
            self.reputation.__gl_address__,
        )

        glstub.call(
            self.reputation, "bind_escrow", self.escrow.__gl_address__, sender=SPONSOR
        )
        self.publish_policy()

    def _render(self, url, mode):
        if self.page_offline:
            raise RuntimeError("render failed")
        return self.page_text

    # -- setup helpers -------------------------------------------------

    def publish_policy(self, **overrides):
        spec = dict(DEFAULT_POLICY)
        spec.update(overrides)
        return glstub.call(
            self.policy,
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
            sender=SPONSOR,
        )

    def create_grant(
        self,
        allocations=(60_000, 40_000),
        criteria_count=3,
        policy_id="standard-v1",
        repo="acme/widget",
    ):
        milestones = []
        for i, allocation in enumerate(allocations):
            milestones.append(
                {
                    "title": f"Milestone {i + 1}",
                    "allocation": str(allocation),
                    "criteria": [
                        f"Requirement {j + 1} for milestone {i + 1} must be demonstrably shipped."
                        for j in range(criteria_count)
                    ],
                }
            )
        return glstub.call(
            self.escrow,
            "create_grant",
            GRANTEE,
            repo,
            "Widget platform grant",
            policy_id,
            json.dumps(milestones),
            90,
            sender=SPONSOR,
            value=sum(allocations),
        )

    def submit(self, grant_id, index=0, tag="v0.2.0", url="https://demo.example/app"):
        return glstub.call(
            self.escrow, "submit_milestone", grant_id, index, tag, url, sender=GRANTEE
        )

    def review(self, grant_id, index=0, sender=STRANGER):
        return glstub.call(self.escrow, "review_milestone", grant_id, index, sender=sender)

    def appeal(self, grant_id, index, rebuttal, bond, url=""):
        return glstub.call(
            self.escrow,
            "file_appeal",
            grant_id,
            index,
            rebuttal,
            url,
            sender=GRANTEE,
            value=bond,
        )

    # -- read helpers --------------------------------------------------

    def milestone(self, grant_id, index=0):
        return glstub.view(self.escrow, "get_milestone", grant_id, index)

    def grant(self, grant_id):
        return glstub.view(self.escrow, "get_grant", grant_id)["grant"]

    def latest_review(self, grant_id, index=0):
        rid = self.milestone(grant_id, index)["latest_review_id"]
        return glstub.view(self.escrow, "get_review", rid)

    def reputation_of(self, address=GRANTEE):
        return glstub.view(self.reputation, "get_reputation", address)

    def appeal_quote(self, grant_id, index=0):
        return glstub.view(self.escrow, "get_appeal_quote", grant_id, index)


@pytest.fixture()
def scenario(world, modules):
    """A funded, policy-bound three-contract deployment ready to review."""
    return Scenario(world, modules)
