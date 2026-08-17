# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""BuilderReputation — the memory half of GrantMilestoneEscrow.

Grant programmes forget. Last year's committee cannot see how last year's calls
were made, so standards drift and a builder who shipped four clean milestones
starts from zero at every new foundation.

This contract is the durable record. It holds no money and makes no judgments;
it only accumulates what the escrow already decided. That separation is
deliberate — a reputation number that could be written by anyone is worth
nothing, so exactly one address is ever allowed to write here.

## Trust model

`bind_escrow` may be called exactly once, by the deployer, and freezes the
writer address forever. After that the deployer has no remaining privilege of
any kind: it cannot rebind, cannot edit a record, cannot delete a builder. The
reputation ledger is therefore as trustworthy as the escrow that feeds it, and
no more — which is the honest ceiling for this kind of data.
"""

import json
from dataclasses import dataclass

from genlayer import *

# Tier labels mirrored from grant_escrow. Duplicated as a literal list rather
# than imported because GenVM modules are deployed independently; a shared
# constant would be a shared deployment dependency for no real benefit.
SETTLEMENT_TIERS = ["COMPLETE", "SUBSTANTIAL", "PARTIAL", "INSUFFICIENT", "REJECTED"]

ZERO_ADDRESS = "0x" + "0" * 40


def _canonical_json(obj: object) -> str:
    """Serialise deterministically so all validators agree byte for byte."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _addr_str(addr: object) -> str:
    """Convert an Address to a stable lowercase hex string."""
    try:
        return str(addr.as_hex).lower()
    except Exception:
        return str(addr).lower()


def _normalize_address_arg(raw: str) -> str:
    """Validate a caller-supplied hex address string and lowercase it."""
    if not isinstance(raw, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_ADDRESS")
    clean = raw.strip().lower()
    if len(clean) != 42 or not clean.startswith("0x"):
        raise gl.vm.UserError("[EXPECTED] INVALID_ADDRESS")
    for ch in clean[2:]:
        if ch not in "0123456789abcdef":
            raise gl.vm.UserError("[EXPECTED] INVALID_ADDRESS")
    if clean == ZERO_ADDRESS:
        raise gl.vm.UserError("[EXPECTED] INVALID_ADDRESS")
    return clean


@allow_storage
@dataclass
class Record:
    """One builder's cumulative track record.

    Counters are `u32` because a builder completing four billion milestones is
    not a case worth carrying an unbounded integer for. Money is `bigint`,
    which has no ceiling to reason about.
    """

    builder: str
    settlements: u32
    complete: u32
    substantial: u32
    partial: u32
    insufficient: u32
    rejected: u32
    clarifications: u32
    appeals_filed: u32
    appeals_upheld: u32
    total_paid: bigint
    first_seen_at: str
    last_seen_at: str


class Contract(gl.Contract):
    """Append-only reputation ledger written exclusively by the bound escrow."""

    deployer: str
    escrow: str
    builder_count: u32
    records: TreeMap[str, Record]
    builder_by_index: TreeMap[str, str]

    def __init__(self):
        self.deployer = _addr_str(gl.message.sender_address)
        self.escrow = ""
        self.builder_count = u32(0)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    @gl.public.write
    def bind_escrow(self, escrow_address: str) -> str:
        """Bind the one address allowed to write records. Callable once, ever."""
        if _addr_str(gl.message.sender_address) != self.deployer:
            raise gl.vm.UserError("[EXPECTED] NOT_DEPLOYER")
        if self.escrow != "":
            raise gl.vm.UserError("[EXPECTED] ESCROW_ALREADY_BOUND")
        bound = _normalize_address_arg(escrow_address)
        self.escrow = bound
        return bound

    def _require_escrow(self) -> None:
        """Reject any writer other than the bound escrow."""
        if self.escrow == "":
            raise gl.vm.UserError("[EXPECTED] ESCROW_NOT_BOUND")
        if _addr_str(gl.message.sender_address) != self.escrow:
            raise gl.vm.UserError("[EXPECTED] NOT_AUTHORIZED_WRITER")

    def _touch(self, builder: str) -> Record:
        """Fetch or lazily create a builder's record."""
        if builder in self.records:
            return self.records[builder]

        now = _now_iso()
        index = int(self.builder_count)
        record = Record(
            builder=builder,
            settlements=u32(0),
            complete=u32(0),
            substantial=u32(0),
            partial=u32(0),
            insufficient=u32(0),
            rejected=u32(0),
            clarifications=u32(0),
            appeals_filed=u32(0),
            appeals_upheld=u32(0),
            total_paid=bigint(0),
            first_seen_at=now,
            last_seen_at=now,
        )
        self.records[builder] = record
        self.builder_by_index[str(index)] = builder
        self.builder_count = u32(index + 1)
        return self.records[builder]

    # ------------------------------------------------------------------
    # Escrow-only writes
    # ------------------------------------------------------------------

    @gl.public.write
    def record_settlement(self, builder_address: str, tier: str, paid_amount: u256) -> None:
        """Record one settled milestone outcome and the amount it released."""
        self._require_escrow()
        builder = _normalize_address_arg(builder_address)

        if not isinstance(tier, str) or tier not in SETTLEMENT_TIERS:
            raise gl.vm.UserError("[EXPECTED] INVALID_TIER")
        amount = int(paid_amount)
        if amount < 0:
            raise gl.vm.UserError("[EXPECTED] INVALID_AMOUNT")

        rec = self._touch(builder)
        rec.settlements = u32(int(rec.settlements) + 1)
        rec.total_paid = bigint(int(rec.total_paid) + amount)
        rec.last_seen_at = _now_iso()

        if tier == "COMPLETE":
            rec.complete = u32(int(rec.complete) + 1)
        elif tier == "SUBSTANTIAL":
            rec.substantial = u32(int(rec.substantial) + 1)
        elif tier == "PARTIAL":
            rec.partial = u32(int(rec.partial) + 1)
        elif tier == "INSUFFICIENT":
            rec.insufficient = u32(int(rec.insufficient) + 1)
        else:
            rec.rejected = u32(int(rec.rejected) + 1)

    @gl.public.write
    def record_clarification(self, builder_address: str) -> None:
        """Record that a review ended unresolved and had to be resubmitted.

        Tracked separately from a rejection: needing a clearer submission is a
        process signal, not a quality verdict, and conflating the two would
        punish builders for validator disagreement they did not cause.
        """
        self._require_escrow()
        builder = _normalize_address_arg(builder_address)
        rec = self._touch(builder)
        rec.clarifications = u32(int(rec.clarifications) + 1)
        rec.last_seen_at = _now_iso()

    @gl.public.write
    def record_appeal(self, builder_address: str, upheld: bool) -> None:
        """Record an appeal and whether the second review upgraded the tier."""
        self._require_escrow()
        builder = _normalize_address_arg(builder_address)
        if not isinstance(upheld, bool):
            raise gl.vm.UserError("[EXPECTED] INVALID_APPEAL_RESULT")

        rec = self._touch(builder)
        rec.appeals_filed = u32(int(rec.appeals_filed) + 1)
        if upheld:
            rec.appeals_upheld = u32(int(rec.appeals_upheld) + 1)
        rec.last_seen_at = _now_iso()

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @gl.public.view
    def get_reputation(self, builder_address: str) -> str:
        """Return one builder's record, or a zeroed record if never seen."""
        builder = _normalize_address_arg(builder_address)
        if builder not in self.records:
            return _canonical_json(_empty_record_dict(builder))
        return _canonical_json(_record_to_dict(self.records[builder]))

    @gl.public.view
    def get_builders(self, cursor: u32, limit: u32) -> str:
        """Paginate every known builder in first-seen order."""
        limit_int = int(limit)
        if limit_int < 1 or limit_int > 50:
            raise gl.vm.UserError("[EXPECTED] INVALID_LIMIT")
        cursor_int = int(cursor)
        total = int(self.builder_count)

        items = []
        if cursor_int < total:
            end = min(cursor_int + limit_int, total)
            for i in range(cursor_int, end):
                addr = self.builder_by_index.get(str(i))
                if addr is not None and addr in self.records:
                    items.append(_record_to_dict(self.records[addr]))

        next_cursor = cursor_int + len(items)
        return _canonical_json(
            {
                "cursor": str(cursor_int),
                "items": items,
                "next_cursor": str(next_cursor) if next_cursor < total else None,
                "total": str(total),
            }
        )

    @gl.public.view
    def get_binding(self) -> str:
        """Expose the trust boundary so a reader can verify it independently."""
        return _canonical_json(
            {
                "deployer": self.deployer,
                "escrow": self.escrow,
                "bound": self.escrow != "",
            }
        )


def _now_iso() -> str:
    """UTC timestamp string."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _empty_record_dict(builder: str) -> dict:
    """Zeroed view payload for a builder with no history yet."""
    return {
        "builder": builder,
        "settlements": "0",
        "complete": "0",
        "substantial": "0",
        "partial": "0",
        "insufficient": "0",
        "rejected": "0",
        "clarifications": "0",
        "appeals_filed": "0",
        "appeals_upheld": "0",
        "total_paid": "0",
        "first_seen_at": "",
        "last_seen_at": "",
        "known": False,
    }


def _record_to_dict(r: Record) -> dict:
    """Flatten a stored Record into JSON-safe decimal strings."""
    return {
        "builder": r.builder,
        "settlements": str(int(r.settlements)),
        "complete": str(int(r.complete)),
        "substantial": str(int(r.substantial)),
        "partial": str(int(r.partial)),
        "insufficient": str(int(r.insufficient)),
        "rejected": str(int(r.rejected)),
        "clarifications": str(int(r.clarifications)),
        "appeals_filed": str(int(r.appeals_filed)),
        "appeals_upheld": str(int(r.appeals_upheld)),
        "total_paid": str(int(r.total_paid)),
        "first_seen_at": r.first_seen_at,
        "last_seen_at": r.last_seen_at,
        "known": True,
    }
