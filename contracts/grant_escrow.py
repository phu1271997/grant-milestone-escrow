# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""GrantEscrow — the money and the jury.

Holds a sponsor's deposit, splits it across milestones whose acceptance criteria
are pinned on-chain, and releases funds only when independent GenLayer
validators — each reading the public evidence with its own LLM — agree on the
*same payout tier*.

See docs/PROBLEM.md for why this cannot be a normal smart contract, and
docs/ARCHITECTURE.md for the consensus design.

Companion contracts:
  * MilestonePolicy   — frozen review rules, read once per review
  * BuilderReputation — durable track record, written after each settlement
"""

import json
from dataclasses import dataclass

from genlayer import *

# ----------------------------------------------------------------------------
# Protocol constants
# ----------------------------------------------------------------------------

BPS_DENOMINATOR = 10000
PERMILLE_DENOMINATOR = 1000

MIN_MILESTONES_PER_GRANT = 1
MAX_MILESTONES_PER_GRANT = 12
MIN_REQUIREMENTS_PER_MILESTONE = 2
MAX_REQUIREMENTS_PER_MILESTONE = 12

MAX_TITLE_LEN = 160
MAX_REQUIREMENT_LEN = 300
MAX_REBUTTAL_LEN = 1200
MAX_URL_LEN = 512
MAX_TAG_LEN = 100
MAX_REPO_LEN = 140
MAX_MILESTONES_JSON_LEN = 16384

# Evidence text is truncated before it reaches the prompt. A validator that
# rendered slightly more of a lazily-loaded page must still see the same leading
# window, otherwise page length alone would drive disagreement.
MAX_RELEASE_NOTES_CHARS = 6000
MAX_EVIDENCE_PAGE_CHARS = 10000

GITHUB_API_BASE = "https://api.github.com/repos/"
GITHUB_UA = "GenLayer-GrantMilestoneEscrow/1.0"

ZERO_ADDRESS = "0x" + "0" * 40

# Grant status
GRANT_ACTIVE = 0
GRANT_CLOSED = 1

# Milestone state machine:
#   OPEN      -> SUBMITTED   (grantee submits evidence)
#   SUBMITTED -> SETTLED     (review reached a tier and paid)
#   SUBMITTED -> OPEN        (review returned NEEDS_CLARIFICATION; retry)
#   SETTLED   -> FINAL       (appeal consumed, or tier was COMPLETE)
MS_OPEN = 0
MS_SUBMITTED = 1
MS_SETTLED = 2
MS_FINAL = 3

TIER_COMPLETE = "COMPLETE"
TIER_SUBSTANTIAL = "SUBSTANTIAL"
TIER_PARTIAL = "PARTIAL"
TIER_INSUFFICIENT = "INSUFFICIENT"
TIER_REJECTED = "REJECTED"
TIER_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"

SETTLEABLE_TIERS = (
    TIER_COMPLETE,
    TIER_SUBSTANTIAL,
    TIER_PARTIAL,
    TIER_INSUFFICIENT,
    TIER_REJECTED,
)

REVIEW_KIND_INITIAL = 0
REVIEW_KIND_APPEAL = 1


# ----------------------------------------------------------------------------
# Deterministic helpers
# ----------------------------------------------------------------------------


def _canonical_json(obj: object) -> str:
    """Serialise deterministically: sorted keys, compact, ASCII-escaped.

    Anything that crosses the leader/validator boundary or lands in storage goes
    through here, so dictionary iteration order can never influence a hash.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(data: str) -> str:
    """SHA-256 hex digest of a UTF-8 string."""
    import hashlib

    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _addr_str(addr: object) -> str:
    """Convert an Address to a stable lowercase hex string.

    `Address.as_hex` exists on current builds but has moved across SDK
    revisions, so the access is guarded rather than assumed.
    """
    try:
        return str(addr.as_hex).lower()
    except Exception:
        return str(addr).lower()


def _normalize_address_arg(raw: str) -> str:
    """Validate and lowercase a caller-supplied hex address."""
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


def _collapse_whitespace(text: str) -> str:
    """Collapse any whitespace run to one ASCII space and trim the ends."""
    return " ".join(text.split())


def _validate_text(raw: str, max_len: int, error_code: str, min_len: int = 1) -> str:
    """Bounded, control-character-free, whitespace-collapsed text."""
    if not isinstance(raw, str):
        raise gl.vm.UserError(f"[EXPECTED] {error_code}")
    for ch in raw:
        cp = ord(ch)
        if (cp < 32 and ch not in ("\t", "\n", "\r")) or cp == 127:
            raise gl.vm.UserError(f"[EXPECTED] {error_code}")
    clean = _collapse_whitespace(raw)
    if len(clean) < min_len or len(clean) > max_len:
        raise gl.vm.UserError(f"[EXPECTED] {error_code}")
    return clean


def _validate_repo(raw: str) -> str:
    """Validate a GitHub `owner/name` slug.

    The repository is the anchor of every evidence fetch, so it is constrained
    to the exact shape GitHub accepts rather than being passed through as a free
    URL fragment. This closes off path traversal into other API endpoints.
    """
    if not isinstance(raw, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
    clean = raw.strip().strip("/")
    if len(clean) < 3 or len(clean) > MAX_REPO_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
    parts = clean.split("/")
    if len(parts) != 2:
        raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
    for part in parts:
        if len(part) < 1 or len(part) > 100:
            raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
        if part.startswith(".") or part.endswith("."):
            raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
        for ch in part:
            if not (ch.isalnum() or ch in ("-", "_", ".")):
                raise gl.vm.UserError("[EXPECTED] INVALID_REPO")
    return clean


def _validate_tag(raw: str) -> str:
    """Validate a git tag name conservatively.

    Deliberately stricter than git itself: the tag is interpolated into an API
    path, so anything that could change the meaning of that path is rejected.
    """
    if not isinstance(raw, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_RELEASE_TAG")
    clean = raw.strip()
    if len(clean) < 1 or len(clean) > MAX_TAG_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_RELEASE_TAG")
    for ch in clean:
        if not (ch.isalnum() or ch in ("-", "_", ".", "+")):
            raise gl.vm.UserError("[EXPECTED] INVALID_RELEASE_TAG")
    if ".." in clean:
        raise gl.vm.UserError("[EXPECTED] INVALID_RELEASE_TAG")
    return clean


def _validate_https_url(raw: str, allow_empty: bool = False) -> str:
    """Validate and normalise a public HTTPS URL.

    Rejects credentials, non-443 ports, fragments, IP literals and localhost, so
    that a submitted "deliverable" cannot point a validator at something only
    that validator can reach.
    """
    import ipaddress
    import urllib.parse

    if allow_empty and (raw is None or (isinstance(raw, str) and raw.strip() == "")):
        return ""
    if not isinstance(raw, str):
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    clean = raw.strip()
    if len(clean) == 0 or len(clean) > MAX_URL_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")

    try:
        parsed = urllib.parse.urlsplit(clean)
    except Exception:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")

    if parsed.scheme != "https":
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")

    host = parsed.hostname
    if not host:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    host = host.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    except ValueError:
        pass

    try:
        port = parsed.port
    except ValueError:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    if port is not None and port != 443:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")

    path = parsed.path if parsed.path else "/"
    normalized = urllib.parse.urlunsplit(("https", host, path, parsed.query, ""))
    if len(normalized) > MAX_URL_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_EVIDENCE_URL")
    return normalized


def _parse_milestone_spec(raw_json: str) -> list:
    """Parse and validate the milestone definition array.

    Milestones arrive as a JSON string rather than a typed list because calldata
    forbids `list[T]` in a public signature, and because the acceptance criteria
    must be stored exactly as the sponsor wrote them — they are the text the
    validators will later be asked to judge against.

    Returns a list of dicts: {"title", "allocation", "criteria": [str, ...]}.
    """
    if not isinstance(raw_json, str) or len(raw_json) > MAX_MILESTONES_JSON_LEN:
        raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONES_JSON")
    try:
        parsed = json.loads(raw_json)
    except Exception:
        raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONES_JSON")
    if not isinstance(parsed, list):
        raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONES_JSON")
    if not (MIN_MILESTONES_PER_GRANT <= len(parsed) <= MAX_MILESTONES_PER_GRANT):
        raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONE_COUNT")

    out = []
    for entry in parsed:
        if not isinstance(entry, dict):
            raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONE_ENTRY")
        if set(entry.keys()) != {"title", "allocation", "criteria"}:
            raise gl.vm.UserError("[EXPECTED] INVALID_MILESTONE_KEYS")

        title = _validate_text(entry["title"], MAX_TITLE_LEN, "INVALID_MILESTONE_TITLE")

        raw_alloc = entry["allocation"]
        if not isinstance(raw_alloc, str) or not raw_alloc.isdigit():
            raise gl.vm.UserError("[EXPECTED] INVALID_ALLOCATION")
        allocation = int(raw_alloc)
        if allocation <= 0:
            raise gl.vm.UserError("[EXPECTED] ZERO_ALLOCATION")

        raw_criteria = entry["criteria"]
        if not isinstance(raw_criteria, list):
            raise gl.vm.UserError("[EXPECTED] INVALID_CRITERIA")
        if not (MIN_REQUIREMENTS_PER_MILESTONE <= len(raw_criteria) <= MAX_REQUIREMENTS_PER_MILESTONE):
            raise gl.vm.UserError("[EXPECTED] INVALID_CRITERIA_COUNT")

        criteria = []
        seen = set()
        for c in raw_criteria:
            clean_c = _validate_text(c, MAX_REQUIREMENT_LEN, "INVALID_CRITERION", min_len=8)
            # Duplicate criteria would let a sponsor inflate the denominator and
            # quietly make a milestone easier or harder than it reads.
            fold = clean_c.lower()
            if fold in seen:
                raise gl.vm.UserError("[EXPECTED] DUPLICATE_CRITERION")
            seen.add(fold)
            criteria.append(clean_c)

        out.append({"title": title, "allocation": allocation, "criteria": criteria})
    return out


def _now_iso() -> str:
    """UTC timestamp string."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_iso_utc(raw: object):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None.

    GitHub returns `...Z`; `datetime.fromisoformat` only learned to accept that
    suffix in newer Python, so it is rewritten explicitly. Returning None rather
    than raising lets callers treat an unparseable timestamp as missing evidence
    instead of as a crash.
    """
    import datetime

    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


# ----------------------------------------------------------------------------
# Storage structs
# ----------------------------------------------------------------------------


@allow_storage
@dataclass
class Grant:
    """A funded grant. `escrowed` is the balance still held for this grant."""

    grant_id: str
    sponsor: str
    grantee: str
    repo: str
    title: str
    policy_id: str
    deposit: bigint
    escrowed: bigint
    released: bigint
    milestone_count: u32
    settled_count: u32
    status: u8
    created_at: str


@allow_storage
@dataclass
class Milestone:
    """One milestone. `criteria_json` is the frozen requirement list."""

    grant_id: str
    index: u32
    title: str
    criteria_json: str
    requirement_count: u32
    allocation: bigint
    state: u8
    release_tag: str
    evidence_url: str
    submitted_at: str
    review_count: u32
    latest_review_id: str
    settled_tier: str
    settled_payout_bps: u32
    paid_amount: bigint
    appeal_filed: bool
    appeal_bond: bigint


@allow_storage
@dataclass
class Review:
    """One consensus-accepted review attempt.

    Stores both what the jury agreed on (`tier`, `payout_bps`, `commit_sha`) and
    the diagnostic detail it did *not* have to agree on (`met_count`,
    `confidence`, the two masks), so a reader can see the reasoning without
    mistaking it for part of the consensus contract.
    """

    review_id: str
    grant_id: str
    milestone_index: u32
    reviewer: str
    kind: u8
    release_tag: str
    commit_sha: str
    evidence_url: str
    evidence_fingerprint: str
    met_count: u32
    total_count: u32
    blocker_mask: u32
    gap_mask: u32
    confidence: u8
    tier: str
    payout_bps: u32
    paid_amount: bigint
    created_at: str


# ----------------------------------------------------------------------------
# Review taxonomy
# ----------------------------------------------------------------------------
#
# The jury never returns a verdict. It returns *observations*, and this module
# turns observations into money by a fixed rule. That split is the whole point:
# if the model chose the payout directly, two validators phrasing the same
# judgment differently would produce two different payouts, and consensus would
# either collapse or have to be weakened until it meant nothing.
#
# Observations come in two flavours:
#
#   * CODE_* keys are decided here, in Python, from fetched metadata. A release
#     published before the grant existed is not a matter of opinion.
#   * LLM_* keys are decided by the model reading the evidence.
#
# Both land in the same bitmask so that downstream logic — and the stored
# record — treats them uniformly.

CODE_BLOCKER_KEYS = [
    # The tagged release predates the grant: the work is being re-submitted.
    "release_predates_grant",
    # The three GitHub views of this tag disagree about which commit it is.
    "source_commit_conflict",
    # The tag resolves, but not to a commit that exists in this repository.
    "commit_not_in_repository",
]

LLM_BLOCKER_KEYS = [
    # Evidence describes a different project than the funded repository.
    "unrelated_repository",
    # The submission does not engage with the acceptance criteria at all.
    "criteria_not_addressed",
    # The deliverable page asserts things the release contradicts.
    "fabricated_evidence",
    # A named artefact is simply absent from the tagged release.
    "artifact_absent_from_release",
]

BLOCKER_KEYS = CODE_BLOCKER_KEYS + LLM_BLOCKER_KEYS

CODE_GAP_KEYS = [
    # A GitHub endpoint did not answer, or answered unusably.
    "release_source_unreachable",
    # The deliverable page did not render.
    "evidence_page_unreachable",
    # The model's JSON was malformed, fenced, or missing keys.
    "llm_output_unusable",
    # The model did not classify every requirement exactly once.
    "requirement_coverage_incomplete",
    # The model invented a requirement id.
    "requirement_id_unknown",
    # The model's own confidence fell under the policy floor.
    "confidence_below_policy_floor",
]

LLM_GAP_KEYS = [
    # Evidence exists but does not let anyone check the claim either way.
    "deliverable_unverifiable",
    # The acceptance criterion itself admits more than one reading.
    "criteria_ambiguous",
]

GAP_KEYS = CODE_GAP_KEYS + LLM_GAP_KEYS

MAX_BLOCKER_MASK = (1 << len(BLOCKER_KEYS)) - 1
MAX_GAP_MASK = (1 << len(GAP_KEYS)) - 1

# Only the LLM_* subsets are accepted from model output. If the model tries to
# assert `release_predates_grant` it is claiming authority over a fact that was
# already settled arithmetically, and the key is refused.
LLM_ALLOWED_BLOCKERS = set(LLM_BLOCKER_KEYS)
LLM_ALLOWED_GAPS = set(LLM_GAP_KEYS)


def _bit(keys: list, name: str) -> int:
    """Bit position of a taxonomy key within its mask."""
    return 1 << keys.index(name)


def _keys_to_mask(keys: list, allowed: set, selected: object, all_keys: list) -> int:
    """Fold a list of taxonomy key strings into a bitmask.

    Unknown or out-of-scope keys are a hard failure rather than a silent skip:
    a model that emits a key this contract does not recognise has not been
    understood, and guessing at its intent is how a review quietly becomes a
    rubber stamp.
    """
    if not isinstance(selected, list):
        raise ValueError("taxonomy selection must be a list")
    mask = 0
    for k in selected:
        if not isinstance(k, str):
            raise ValueError("taxonomy key must be a string")
        if k not in allowed:
            raise ValueError(f"taxonomy key out of scope: {k}")
        mask |= _bit(all_keys, k)
    return mask


def _derive_settlement(
    met_count: int,
    total_count: int,
    blocker_mask: int,
    gap_mask: int,
    substantial_permille: int,
    partial_permille: int,
    substantial_payout_bps: int,
    partial_payout_bps: int,
) -> tuple:
    """Turn observations into (tier, payout_bps) by fixed precedence.

    Precedence, highest first:

      1. Any gap        -> NEEDS_CLARIFICATION. Nothing is paid and nothing is
                           held against the builder; the submission is retried.
      2. Any blocker    -> REJECTED. The evidence is disqualifying, not merely
                           incomplete.
      3. Completion band -> COMPLETE / SUBSTANTIAL / PARTIAL / INSUFFICIENT.

    Gaps outrank blockers deliberately. "I could not read the evidence" must
    never be allowed to harden into "the work is disqualified", because the
    second is a permanent mark and the first is a network hiccup.

    All arithmetic is integer. Floats are forbidden in contract signatures and
    would in any case make two validators disagree over a rounding bit.
    """
    if gap_mask != 0:
        return (TIER_NEEDS_CLARIFICATION, 0)
    if blocker_mask != 0:
        return (TIER_REJECTED, 0)
    if total_count <= 0 or met_count < 0 or met_count > total_count:
        return (TIER_NEEDS_CLARIFICATION, 0)

    permille = (met_count * PERMILLE_DENOMINATOR) // total_count
    if permille >= PERMILLE_DENOMINATOR:
        return (TIER_COMPLETE, BPS_DENOMINATOR)
    if permille >= substantial_permille:
        return (TIER_SUBSTANTIAL, substantial_payout_bps)
    if permille >= partial_permille:
        return (TIER_PARTIAL, partial_payout_bps)
    return (TIER_INSUFFICIENT, 0)
