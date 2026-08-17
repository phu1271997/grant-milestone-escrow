# Architecture

## The shape of it

```
Sponsor ──create_grant (payable)──┐
                                  ▼
Builder ──submit_milestone──▶ ┌─────────────────┐ ──view──▶ MilestonePolicy
                              │   GrantEscrow   │             (frozen rules)
Anyone  ──review_milestone──▶ │   money + jury  │
                              │                 │ ──write─▶ BuilderReputation
Builder ──file_appeal ───────▶└────────┬────────┘             (track record)
          (payable, bonded)            │
                                       │ gl.vm.run_nondet_default
                                       ▼
                    ┌──────────────────────────────────────┐
                    │ Every validator, independently:      │
                    │  1. GitHub Releases API   (announce) │
                    │  2. GitHub git ref API    (identity) │
                    │  3. GitHub Commits API    (existence)│
                    │  4. render the deliverable page      │
                    │  5. its own LLM over the criteria    │
                    │  6. derive a payout tier             │
                    └──────────────────────────────────────┘
                                       │
                        agree on the tier, or nothing moves
```

Three contracts, one non-deterministic block, no backend, no oracle, no
indexer, no relayer.

---

## Why three contracts

| Contract | Holds | Why it is separate |
|---|---|---|
| `MilestonePolicy` | Review rules | The rules a grant is judged by must not be editable by whoever holds the money. A grant pins a policy id at funding, and a published policy is immutable, so acceptance criteria cannot drift after work starts. |
| `GrantEscrow` | The deposit and the jury | The only contract that can move money, and the only one that runs non-deterministic code. |
| `BuilderReputation` | Track record | A reputation number anyone can write is worth nothing. Exactly one address may write here, bound once and frozen. Keeping it out of the escrow also means a bug in bookkeeping cannot corrupt custody. |

The escrow reads the policy through `gl.get_contract_at(...).view()` **before**
any non-deterministic block, and writes to the reputation ledger through
`.emit()` after settlement. Reputation writes are best-effort and wrapped: a
ledger that rejects a write must never be able to strand a payout that consensus
already authorised.

---

## The core mechanism

### The model never returns a verdict

The prompt asks for observations, and only observations:

```json
{
  "met":        ["R1", "R3", "R4"],
  "unmet":      ["R2"],
  "blockers":   [],
  "gaps":       [],
  "confidence": 84
}
```

The contract turns that into money by a fixed rule. The model is never shown
the tier names, the payout bands, the allocation, or the word "escrow" — it
cannot aim at an outcome it has not been told exists.

If the model chose the payout directly, two validators phrasing the same
judgment differently would produce two different payouts, and consensus would
either collapse or have to be weakened until it meant nothing.

### Observations have owners

Some findings are not opinions. Whether a release was published before the grant
existed is arithmetic, and the contract decides it from fetched timestamps.
Those keys are in `CODE_BLOCKER_KEYS` / `CODE_GAP_KEYS`, and the parser
**refuses** them if the model tries to assert one — a model claiming standing
over a settled fact has misunderstood its job, and the whole response is
discarded as unusable rather than partially trusted.

When an arithmetic blocker fires, inference is skipped entirely. There is
nothing left to weigh, and asking anyway would only create an opportunity to
argue with a fact.

### Precedence

```
any gap      -> NEEDS_CLARIFICATION   nothing paid, nothing held against anyone
any blocker  -> REJECTED              the evidence is disqualifying
otherwise    -> band by met/total     COMPLETE / SUBSTANTIAL / PARTIAL / INSUFFICIENT
```

Gaps outrank blockers deliberately. *"I could not read the evidence"* must never
harden into *"the work is disqualified"*, because the second is a permanent mark
and the first is a network hiccup.

Bands are integer permille of requirements met, compared against the pinned
policy. No floats anywhere: they are barred from contract signatures, and they
would put two validators on opposite sides of a rounding bit.

### What validators must agree on

```python
def _agrees(leader_result):
    ...
    for key in ("commit_sha", "evidence_fingerprint"):
        if leader.get(key) != mine.get(key):
            return False
    return _settlement_of(leader) == _settlement_of(mine)
```

Two things, and nothing else:

1. **Which immutable objects were read** — the resolved commit SHA and a
   fingerprint over the evidence *identity*.
2. **What those observations pay out** — the `(tier, payout_bps)` pair.

The validator does **not** compare `met_count`, the observation masks, or
`confidence`. Two validators may disagree about whether requirement R3 was
satisfied and still settle, if both readings land in SUBSTANTIAL. That is
agreement about the only thing with consequences.

Two validators landing on COMPLETE and PARTIAL differ by a quarter of the
milestone. The transaction fails. Nothing is paid, no review is recorded, and
the milestone stays where it was — the builder resubmits with clearer evidence
rather than being paid on whichever validator happened to lead.

`tests/test_consensus.py` pins both halves of that property.

### Evidence is fingerprinted by identity, not content

Two validators rendering the same live page a second apart see different bytes.
Hashing that text would make agreement impossible. What can be pinned is which
immutable objects were consulted:

```
sha256({repo, tag, commit_sha, published_at, evidence_url})
```

The page content still reaches the model — it is evidence — but it never enters
the identity that consensus turns on.

### Cross-checking three views of one tag

| Endpoint | Answers |
|---|---|
| `releases/tags/{tag}` | when it was announced, and the release notes |
| `git/ref/tags/{tag}` | which object the tag names (annotated tags dereferenced) |
| `commits/{sha}` | that the object is a commit **in this repository** |

One view would be enough to read a number off. Three are used because the
interesting failures are the disagreements between them: a tag moved after the
announcement (commit newer than the release), or a SHA that does not live in the
funded repository.

---

## Prompt injection

Untrusted material — release notes, the rendered deliverable page, an appeal
rebuttal — is wrapped in a fence derived from the evidence fingerprint:

```
<<<a91f3c07b2e4d518:RELEASE_NOTES>>>
…untrusted text…
<<<a91f3c07b2e4d518:END>>>
```

Every validator computes the same fence from the same immutable evidence, but a
builder writing "ignore previous instructions" into a release note cannot know
it in advance, so injected text cannot close the block it is quoted inside.

The prompt also names the boundary explicitly: only the instruction block has
authority, and quoted data claiming otherwise is to be ignored.

---

## The appeal forum

An appeal exists so a "no" is not final. A bond exists so an appeal is not free.

| Second jury says | Bond | Money |
|---|---|---|
| A higher tier | refunded | the difference is released |
| The same or lower tier | forfeited to the grant balance | nothing changes |
| `NEEDS_CLARIFICATION` | refunded, **appeal not consumed** | nothing changes |

Three consequences worth stating:

- **An appeal can only raise the tier.** Risking a clawback would kill the forum
  — nobody appeals a partial payment if losing costs them what they already have.
- **A forfeited bond never becomes anyone's profit.** It returns to the grant
  balance, which returns to the sponsor at close. The bond prices the retry; it
  does not fund anyone.
- **An unreadable second review costs nothing.** The builder does not pay for the
  network being down, so the appeal stays available.

One appeal per milestone.

---

## Edge cases and where they are handled

| Case | Handling |
|---|---|
| GitHub endpoint unreachable | gap → `NEEDS_CLARIFICATION`, retry |
| Deliverable page down | gap → `NEEDS_CLARIFICATION`, retry |
| Model returns fenced markdown / bad JSON / missing keys | gap → `NEEDS_CLARIFICATION` |
| Model invents a requirement id | gap `requirement_id_unknown` — the whole split is void |
| Model classifies a requirement twice, or misses one | gap `requirement_coverage_incomplete` |
| Model reports low confidence | gap `confidence_below_policy_floor` |
| Model asserts a code-decided blocker | response discarded as unusable |
| Release predates the grant | blocker, decided arithmetically, no inference |
| Tag moved after its release | blocker `source_commit_conflict` |
| Tag points outside the repository | blocker `commit_not_in_repository` |
| Draft release | treated as absent, not as weak evidence |
| Allocations do not sum to the deposit | `ALLOCATION_DEPOSIT_MISMATCH` at creation |
| Zero deposit, zero allocation | rejected at creation |
| Duplicate acceptance criteria | rejected at creation — a repeat would move the bands |
| Sponsor funding themselves | rejected at creation |
| Reviewing an unsubmitted milestone | `MILESTONE_NOT_SUBMITTED` |
| Reviewing a settled milestone again | `MILESTONE_NOT_SUBMITTED` — no double payout |
| Endless re-rolls of a stalled review | capped by the policy's `max_reviews_per_milestone` |
| Wrong appeal bond | exact match required; over- and under-payment both rejected |
| Second appeal | `MILESTONE_NOT_APPEALABLE` |
| Builder never submits | sponsor closes after the deadline |
| Reputation ledger broken or unbound | write swallowed; the payout stands |

---

## SDK version handling

The two `run_nondet` variants swapped names between SDK generations:

| | sandboxed validator | no sandbox |
|---|---|---|
| v0.2.x | `run_nondet` | `run_nondet_unsafe` |
| v0.3.0 | `run_nondet_default` | `run_nondet` |

Code written against v0.2.x that calls `run_nondet` silently loses its sandbox
on upgrade. `_run_nondet_sandboxed` prefers `run_nondet_default` when present
and falls back otherwise, which selects the sandboxed variant on both.

This is not pedantry. Without the sandbox, a bug in `validator_fn` is reported
as `Disagree` — indistinguishable from a genuinely split jury, which is the one
signal this contract most needs to be able to read.

Similar guards exist for `Address.as_hex`, the `emit_transfer` call shape, and
the typed-versus-untyped contract proxy. Each is a place the SDK has moved, and
each is documented at the call site rather than left as a mysterious `try`.

---

## Testing strategy

Two layers, deliberately.

**`tests/genlayer_stub.py`** runs the *same contract source* under plain pytest
in milliseconds. Consensus genuinely executes — leader, then validator re-running
the observation — so a validator that agrees too readily fails a test rather
than hiding behind a happy-path demo. Cross-contract calls dispatch into the
real companion contract with the sender rewritten to the calling contract, so
authorisation guards are exercised. Value transfers debit the payer, so an
overspend surfaces as a negative balance.

The shim is deliberately no more forgiving than the GenVM: storage `TreeMap`s
are pre-created by the base class, so a contract that wrongly assigned them in
`__init__` would still fail on chain.

**`gltest --network studionet`** is the real thing, and the only place gas,
finality, validator diversity and live inference exist. What the shim cannot
model is exactly the list of reasons to run it before shipping.
