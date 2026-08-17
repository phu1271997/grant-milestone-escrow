# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""MilestonePolicy — the rulebook half of GrantMilestoneEscrow.

This contract holds no money and performs no non-deterministic work. It exists
so that the *rules* of a review (how many requirements make a tier, how sure the
jury has to be, what an appeal costs) live somewhere separate from the *money*.

Two properties matter and are enforced here:

1. **Append-only.** A published policy can never be edited. A grant pins a
   policy id at creation time, so the rules that grant will be judged under are
   frozen the moment the sponsor funds it. This is the direct answer to the
   "moving goalposts" failure mode in docs/PROBLEM.md.
2. **Publishable once.** `publish_policy` rejects an id that already exists, so
   there is no version of this contract in which a policy silently changes
   underneath a live grant.

The publisher is recorded at construction and is the only account allowed to add
new policies. It cannot alter or remove existing ones, so this is an *additive*
privilege, not an override.
"""

import json
from dataclasses import dataclass

from genlayer import *

# Basis points denominator used across the system (10000 bps == 100%).
BPS_DENOMINATOR = 10000

# Guard rails on policy parameters. These are protocol-level, not per-policy:
# a publisher cannot define a policy that pays out on a coin flip, nor one that
# is impossible to ever satisfy.
MIN_CONFIDENCE_THRESHOLD = 50
MAX_CONFIDENCE_THRESHOLD = 100
MIN_SUBSTANTIAL_PERMILLE = 600
MAX_APPEAL_BOND_BPS = 5000
MAX_POLICY_ID_LEN = 64
MAX_LABEL_LEN = 200


def _canonical_json(obj: object) -> str:
    """Serialise deterministically: sorted keys, no padding, ASCII-escaped.

    Every validator must produce byte-identical output for identical input, so
    dictionary iteration order can never be allowed to leak into a stored value.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _addr_str(addr: object) -> str:
    """Convert an Address to a stable lowercase hex string.

    `Address.as_hex` is present on current builds but has moved between SDK
    revisions, so the attribute access is guarded rather than assumed.
    """
    try:
        return str(addr.as_hex).lower()
    except Exception:
        return str(addr).lower()


def _validate_policy_id(policy_id: str) -> str:
    """Policy ids are short, lowercase, and URL-safe so they can appear in views."""
    if not isinstance(policy_id, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_POLICY_ID")
    clean = policy_id.strip().lower()
    if len(clean) < 3 or len(clean) > MAX_POLICY_ID_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_POLICY_ID")
    for ch in clean:
        if not (ch.isalnum() or ch in ("-", "_", ".")):
            raise gl.vm.UserError("[EXPECTED] INVALID_POLICY_ID")
    return clean


def _validate_label(label: str) -> str:
    """Human-readable description; bounded and free of control characters."""
    if not isinstance(label, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_LABEL")
    clean = " ".join(label.split())
    if len(clean) < 1 or len(clean) > MAX_LABEL_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_LABEL")
    return clean


@allow_storage
@dataclass
class Policy:
    """A frozen set of review rules.

    Thresholds are expressed in permille of *requirements met* rather than in
    basis points, to keep them visually distinct from the payout basis points
    they map onto. `substantial_permille=750` means "three quarters of the
    listed acceptance criteria".
    """

    policy_id: str
    label: str
    substantial_permille: u32
    partial_permille: u32
    substantial_payout_bps: u32
    partial_payout_bps: u32
    confidence_threshold: u8
    appeal_bond_bps: u32
    min_appeal_bond: bigint
    max_reviews_per_milestone: u32
    publisher: str
    created_at: str


class Contract(gl.Contract):
    """Append-only registry of milestone review policies."""

    publisher: str
    policy_count: u32
    policies: TreeMap[str, Policy]
    policy_id_by_index: TreeMap[str, str]

    def __init__(self):
        # TreeMap fields are auto-initialised empty by the GenVM and must not be
        # assigned here (doing so trips `AssertionError: TreeMap <- TreeMap`).
        self.publisher = _addr_str(gl.message.sender_address)
        self.policy_count = u32(0)

    @gl.public.write
    def publish_policy(
        self,
        policy_id: str,
        label: str,
        substantial_permille: u32,
        partial_permille: u32,
        substantial_payout_bps: u32,
        partial_payout_bps: u32,
        confidence_threshold: u8,
        appeal_bond_bps: u32,
        min_appeal_bond: u256,
        max_reviews_per_milestone: u32,
    ) -> str:
        """Publish a new immutable policy. Fails if the id is already taken."""
        if _addr_str(gl.message.sender_address) != self.publisher:
            raise gl.vm.UserError("[EXPECTED] NOT_PUBLISHER")

        clean_id = _validate_policy_id(policy_id)
        if clean_id in self.policies:
            raise gl.vm.UserError("[EXPECTED] POLICY_ALREADY_EXISTS")
        clean_label = _validate_label(label)

        sub_permille = int(substantial_permille)
        part_permille = int(partial_permille)
        sub_bps = int(substantial_payout_bps)
        part_bps = int(partial_payout_bps)
        confidence = int(confidence_threshold)
        bond_bps = int(appeal_bond_bps)
        min_bond = int(min_appeal_bond)
        max_reviews = int(max_reviews_per_milestone)

        # Tier bands must be strictly ordered and must sit above a coin flip.
        # A policy where "half the work" pays "most of the money" is refused at
        # the protocol level rather than left to the publisher's good taste.
        if not (MIN_SUBSTANTIAL_PERMILLE <= sub_permille < 1000):
            raise gl.vm.UserError("[EXPECTED] INVALID_SUBSTANTIAL_BAND")
        if not (0 < part_permille < sub_permille):
            raise gl.vm.UserError("[EXPECTED] INVALID_PARTIAL_BAND")
        if not (0 < part_bps < sub_bps < BPS_DENOMINATOR):
            raise gl.vm.UserError("[EXPECTED] INVALID_PAYOUT_BANDS")
        if not (MIN_CONFIDENCE_THRESHOLD <= confidence <= MAX_CONFIDENCE_THRESHOLD):
            raise gl.vm.UserError("[EXPECTED] INVALID_CONFIDENCE_THRESHOLD")
        if not (0 < bond_bps <= MAX_APPEAL_BOND_BPS):
            raise gl.vm.UserError("[EXPECTED] INVALID_APPEAL_BOND_BPS")
        if min_bond <= 0:
            raise gl.vm.UserError("[EXPECTED] INVALID_MIN_APPEAL_BOND")
        if not (1 <= max_reviews <= 10):
            raise gl.vm.UserError("[EXPECTED] INVALID_MAX_REVIEWS")

        index = int(self.policy_count)
        self.policies[clean_id] = Policy(
            policy_id=clean_id,
            label=clean_label,
            substantial_permille=u32(sub_permille),
            partial_permille=u32(part_permille),
            substantial_payout_bps=u32(sub_bps),
            partial_payout_bps=u32(part_bps),
            confidence_threshold=u8(confidence),
            appeal_bond_bps=u32(bond_bps),
            min_appeal_bond=bigint(min_bond),
            max_reviews_per_milestone=u32(max_reviews),
            publisher=self.publisher,
            created_at=_now_iso(),
        )
        self.policy_id_by_index[str(index)] = clean_id
        self.policy_count = u32(index + 1)
        return clean_id

    @gl.public.view
    def get_policy(self, policy_id: str) -> str:
        """Return one policy as canonical JSON, or raise if unknown."""
        clean_id = _validate_policy_id(policy_id)
        if clean_id not in self.policies:
            raise gl.vm.UserError("[EXPECTED] POLICY_NOT_FOUND")
        return _canonical_json(_policy_to_dict(self.policies[clean_id]))

    @gl.public.view
    def policy_exists(self, policy_id: str) -> bool:
        """Cheap existence probe used by GrantEscrow before pinning a policy."""
        try:
            clean_id = _validate_policy_id(policy_id)
        except Exception:
            return False
        return clean_id in self.policies

    @gl.public.view
    def get_policies(self) -> str:
        """Return every published policy, oldest first."""
        items = []
        for i in range(int(self.policy_count)):
            pid = self.policy_id_by_index.get(str(i))
            if pid is not None and pid in self.policies:
                items.append(_policy_to_dict(self.policies[pid]))
        return _canonical_json({"items": items, "total": str(int(self.policy_count))})


def _now_iso() -> str:
    """UTC timestamp string. Imported locally to keep module scope minimal."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _policy_to_dict(p: Policy) -> dict:
    """Flatten a stored Policy into JSON-safe primitives.

    Integers are emitted as decimal strings so that a JavaScript client reading
    a view can never silently lose precision on a `bigint` field.
    """
    return {
        "policy_id": p.policy_id,
        "label": p.label,
        "substantial_permille": str(int(p.substantial_permille)),
        "partial_permille": str(int(p.partial_permille)),
        "substantial_payout_bps": str(int(p.substantial_payout_bps)),
        "partial_payout_bps": str(int(p.partial_payout_bps)),
        "confidence_threshold": str(int(p.confidence_threshold)),
        "appeal_bond_bps": str(int(p.appeal_bond_bps)),
        "min_appeal_bond": str(int(p.min_appeal_bond)),
        "max_reviews_per_milestone": str(int(p.max_reviews_per_milestone)),
        "publisher": p.publisher,
        "created_at": p.created_at,
    }
