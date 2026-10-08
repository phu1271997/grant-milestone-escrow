# GrantMilestoneEscrow

A grant escrow that releases money only when independent AI validators — each
reading the public evidence themselves — agree on how complete the work is.

Built on **GenLayer**, deployed on **GenLayer Studionet**.

> **Why this dies without GenLayer:** the entire product is a judgment about
> whether *"ship v0.2 with wallet authentication and a public demo"* was
> actually done. Remove the on-chain LLM and web access and there is no verdict,
> no dispute forum, and nothing to release the money against. Replace GenLayer
> consensus with an off-chain oracle and you have not removed the trusted
> reviewer — you have only moved them behind an API.

---

## Links

| | |
|---|---|
| Live app | https://grant-milestone-escrow-nu.vercel.app |
| Source | https://github.com/phu1271997/grant-milestone-escrow |
| Network | GenLayer Studionet, chain id `61999` |
| Demo video | _(fill in)_ |

Deployed contracts:

| Contract | Address |
|---|---|
| `GrantEscrow` | [`0x57c7fA920F4407d084E47ED5E05fCfc7d56D9e00`](https://explorer-studio.genlayer.com/address/0x57c7fA920F4407d084E47ED5E05fCfc7d56D9e00) |
| `MilestonePolicy` | [`0xb757eC8a9824Eb956072d7E6Bc5D5bC4ad597CAb`](https://explorer-studio.genlayer.com/address/0xb757eC8a9824Eb956072d7E6Bc5D5bC4ad597CAb) |
| `BuilderReputation` | [`0xea3DDF603bBDFDcdEA1a9F92FCeE95c42C3daC26`](https://explorer-studio.genlayer.com/address/0xea3DDF603bBDFDcdEA1a9F92FCeE95c42C3daC26) |

Verify the wiring yourself, without a wallet:

```bash
cd frontend && npm ci && cd ..
node scripts/verify-deployment.mjs \
  0x57c7fA920F4407d084E47ED5E05fCfc7d56D9e00 \
  0xb757eC8a9824Eb956072d7E6Bc5D5bC4ad597CAb \
  0xea3DDF603bBDFDcdEA1a9F92FCeE95c42C3daC26
```

---

## The problem

A DAO awards a grant: *"$12,000 when you ship v0.2 with wallet authentication, a
public demo deployment, and automated test coverage over the auth module."*

Three months later the builder says "done". Somebody now has to decide whether
that sentence is true — and in practice that somebody is one reviewer who knows
the builder, reading a repository at 11pm, with no obligation to explain
themselves and no forum for the builder to appeal to.

The failure modes are familiar to anyone who has run a grants programme:
reviewer capture, acceptance criteria that drift after the work starts, release
tags created purely as evidence, no appeal, and no record that next year's
committee can learn from.

Deterministic code can hold the money. It cannot read the sentence.

Full write-up: [docs/PROBLEM.md](docs/PROBLEM.md).

---

## How it works

1. **A sponsor funds a grant** and pins each milestone's acceptance criteria on
   chain — the sentences themselves, not a hash of them, because they are what
   the jury will read. The deposit must equal the sum of the allocations
   exactly, and a published policy freezes the review rules for the life of the
   grant.
2. **The builder submits a release tag** and, optionally, a deliverable URL.
3. **Anyone convenes the jury.** Inside a single non-deterministic block, every
   validator independently fetches three GitHub views of that tag, renders the
   deliverable page, and runs its own LLM over the pinned criteria.
4. **The contract turns observations into a payout tier** by a fixed rule the
   model never sees. Money moves only if validators agree on that tier *and* on
   which commit they read.
5. **The builder can appeal** by posting a bond, once per milestone. A milestone
   settled below `COMPLETE` opens a **14-day appeal window**, and the sponsor
   cannot close the grant — or reclaim the escrow the appeal would be paid from —
   while that window is open. Closing is only possible once every milestone is
   final (appealed or past its window) or the grant deadline has passed.

Outcomes: `COMPLETE` · `SUBSTANTIAL` · `PARTIAL` · `INSUFFICIENT` · `REJECTED` ·
`NEEDS_CLARIFICATION`.

---

## The one design decision worth reading

**The model never returns a verdict.** It returns observations:

```json
{ "met": ["R1","R3","R4"], "unmet": ["R2"], "blockers": [], "gaps": [], "confidence": 84 }
```

The contract derives `(tier, payout_bps)` from those by a fixed rule. The model
is never shown the tier names, the payout bands, or the allocation — it cannot
aim at an outcome it has not been told exists.

Validators then compare **two things and nothing else**: which immutable objects
were read, and what the observations pay out.

```python
for key in ("commit_sha", "evidence_fingerprint"):
    if leader.get(key) != mine.get(key):
        return False
return _settlement_of(leader) == _settlement_of(mine)
```

They do *not* compare requirement counts, observation masks, or confidence. Two
validators can disagree about whether requirement R3 was satisfied and still
settle, if both readings land in `SUBSTANTIAL` — that is agreement about the
only thing with consequences. Two validators landing on `COMPLETE` and `PARTIAL`
differ by a quarter of the milestone, and the transaction fails rather than
paying out on a split jury.

Both halves of that property are pinned in
[`tests/test_consensus.py`](tests/test_consensus.py).

Some findings are not the model's to make. Whether a release predates its grant
is arithmetic, decided from fetched timestamps; the parser **refuses** those keys
if the model asserts them, and skips inference entirely when one fires.

Everything else: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Layout

```
contracts/
  grant_escrow.py         money, the jury, appeals
  milestone_policy.py     append-only review rules
  builder_reputation.py   escrow-bound track record
frontend/                 Vite + React + genlayer-js
tests/                    139 offline tests, plus the runtime shim they run on
tests_onchain/            the same flow against real validators, via gltest
scripts/                  policy bootstrap values, deployment verifier
docs/                     problem, architecture, deploy runbook, demo script
```

---

## Run it

### Contracts

```bash
python3 -m pytest
```

139 tests, no network, no key, under a second. They run the real contract source
against an in-process GenLayer shim that genuinely executes consensus — the
validator re-runs the observation, so a validator that agrees too readily fails
a test instead of hiding behind a happy path.

Against the real network:

```bash
gltest --network studionet tests_onchain/
```

The on-chain suite covers what the shim cannot: gas, finality, validator
diversity, live inference and cross-contract messages passing through consensus.
It needs a funded Studionet account. By definition it has never run offline, so
run it once after deploying and before recording anything.

### Frontend

```bash
cd frontend
cp .env.example .env.local     # fill in the three deployed addresses
npm ci
npm run dev
```

Browsing the registry is read-only and needs no wallet. Connect one only to
fund, submit, review or appeal.

`.env.local` holds addresses and nothing else. Anything prefixed `VITE_` is
compiled into the shipped bundle and is publicly readable, so no key belongs
there — MetaMask signs every write.

### Deploy

[docs/DEPLOY-STUDIONET.md](docs/DEPLOY-STUDIONET.md) — five ordered steps, then:

```bash
node scripts/verify-deployment.mjs <escrow> <policy> <reputation>
```

---

## Trust boundaries

- The **contract** decides every tier. The frontend reads state and never
  computes a verdict.
- No caller can supply a tier, a payout, an observation mask, or a commit SHA.
- The escrow has **no owner and no admin key**. There is no pause, no override,
  no upgrade path, and no migration — which is also why a redeployed escrow
  abandons the grants held by the old one.
- The reputation ledger accepts writes from exactly one address, bound once by
  its deployer, after which that deployer holds no privilege at all.
- Published policies are immutable. A grant is judged by the rules it pinned at
  funding time.
- Web content is untrusted throughout: fenced with a marker derived from the
  evidence, constrained to a validated schema, and never able to close its own
  quoting block.
- Finality is not success. The frontend checks the receipt's execution result,
  because a transaction can finalize having reverted inside the GenVM.

---

## Known limitations

- **GitHub only.** Evidence is anchored to GitHub releases. GitLab, Codeberg and
  self-hosted forges would each need their own cross-check, since the value is
  in the disagreements *between* endpoints, not in any one of them.
- **A milestone is one release tag.** Work spread across several tags cannot be
  submitted as a single milestone today.
- **Criteria quality is load-bearing.** Vague acceptance criteria produce
  low-confidence juries, which stall rather than pay. That is the correct
  behaviour and it is also, unavoidably, a usability cost passed to sponsors.
- **The jury reads what is published, not what was built.** A release whose
  notes overstate the code can pass on the release side; the cross-check against
  the deliverable page is the mitigation, not a proof.
- **Deadlock is a real outcome.** Validators who never converge leave a milestone
  unsettled until the evidence is clarified. That is the intended trade — the
  alternative is paying out on a split jury — but it means a sponsor's money can
  sit longer than a human reviewer would have taken.
- **No partial-appeal path.** An appeal is one shot per milestone, all or
  nothing.

---

## Before submitting

- [ ] Three contracts deployed to Studionet; every transaction shows
      `Result: SUCCESS`, not merely `Status: FINALIZED`
- [ ] `scripts/verify-deployment.mjs` passes every check
- [ ] `gltest --network studionet tests_onchain/` has been run at least once
- [ ] Frontend deployed with the three `VITE_` addresses set in the host's
      environment, and rebuilt after setting them
- [ ] Demo recorded with **two** funded wallets — sponsor and builder are
      visibly different accounts
- [ ] The links table at the top of this file is filled in
- [ ] Nothing anywhere says "testnet". This is Studionet.

## Licence

MIT. See [LICENSE](LICENSE).

Not affiliated with GitHub or with any grants programme.
