# Deploying to GenLayer Studionet

Everything in this project lives on **Studionet** — the hosted network behind
`https://studio.genlayer.com`, chain id `61999`. Contracts, the frontend's
chain, the demo wallet's balance and the funding source are all the same
network. Studionet and the public testnets are separate universes: a contract
deployed here exists only here, and the public testnet faucet funds a different
chain entirely.

Three contracts deploy in a fixed order, because two of them have to be told
about each other.

---

## 0. Before you start

- A MetaMask account with a **GEN balance on Studionet**. Fund it from the
  Studio **Accounts** panel by transferring from a pre-funded Studio account.
  Do not use the public testnet faucet, and do not generate a burner in the
  browser — a fresh address starts at zero and the hosted RPC will not fund it.
- Studio open at `https://studio.genlayer.com/contracts`.

Open Studio's default contract template and check the header it ships with. If
it carries a version pragma line above the `Depends` comment, add the same line
to the top of each of our three contract files before deploying. The `Depends`
hash pins the GenVM runner; the pragma pins the Studio build, and Studio bumps
it independently of anything in this repository.

If a deploy fails in a way that makes no sense, before debugging the contract:
**Settings → Reset Storage → Confirm**, then hard-refresh, then deploy a trivial
one-field contract to prove the environment works.

---

## 1. Deploy `MilestonePolicy`

No constructor arguments.

```
contracts/milestone_policy.py
```

After the transaction appears in the sidebar, **click it** and read the
`Result` field. `Status: FINALIZED` on its own is not success — a transaction
can finalize having reverted. You want `Result: SUCCESS`.

Record the address as `POLICY_ADDRESS`.

## 2. Publish at least one policy

Call `publish_policy` with the arguments from
[`scripts/bootstrap-policy.json`](../scripts/bootstrap-policy.json). The
`standard-v1` block is the one the demo script assumes.

Read the numbers before you send. A published policy can never be edited, and
any grant funded against that id is judged by exactly those numbers for the rest
of its life. That immutability is the feature — it is what stops acceptance
criteria drifting after work has started — but it does mean a typo here is
permanent and the fix is a new policy id.

## 3. Deploy `BuilderReputation`

No constructor arguments.

```
contracts/builder_reputation.py
```

Record the address as `REPUTATION_ADDRESS`.

## 4. Deploy `GrantEscrow`

Two constructor arguments, in this order:

| Argument | Value |
|---|---|
| `policy_contract` | `POLICY_ADDRESS` from step 1 |
| `reputation_contract` | `REPUTATION_ADDRESS` from step 3 |

```
contracts/grant_escrow.py
```

Record the address as `ESCROW_ADDRESS`.

## 5. Bind the escrow to the reputation ledger

On the **BuilderReputation** contract, call:

```
bind_escrow(ESCROW_ADDRESS)
```

This is callable exactly once, by the account that deployed the ledger. After
it, that account has no privilege at all — it cannot rebind, edit a record, or
delete a builder. If you get the address wrong here, the ledger is permanently
bound to the wrong escrow and you need to redeploy it and the escrow.

Which is exactly why step 6 exists.

## 6. Verify the wiring

Three contracts that have to know about each other have one interesting failure
mode: they all deploy cleanly and are pointed at the wrong addresses. Nothing
errors. The escrow just writes reputation records into the void, and you find
out during the demo.

```bash
cd frontend && node ../scripts/verify-deployment.mjs <escrow> <policy> <reputation>
```

Every check must pass before you go further.

## 7. Point the frontend at the deployment

```bash
cd frontend
cp .env.example .env.local
```

Fill in the three addresses:

```
VITE_ESCROW_ADDRESS=0x…
VITE_POLICY_ADDRESS=0x…
VITE_REPUTATION_ADDRESS=0x…
```

There is no key in that file and there must never be one. Anything prefixed
`VITE_` is compiled into the shipped bundle and is readable by anyone who opens
DevTools. MetaMask signs every write; the app only ever holds addresses.

```bash
npm ci
npm run dev
```

## 8. Deploy the frontend

```bash
cd frontend
npx vercel --prod
```

Set the same three `VITE_` variables in the Vercel project's environment
settings, then redeploy so the build picks them up.

---

## Redeploying a contract

The escrow's companion addresses are set at construction and never change. That
is deliberate — a mutable pointer to the contract that decides your payout bands
would be a back door — but it means:

- Redeploying **MilestonePolicy** or **BuilderReputation** requires redeploying
  **GrantEscrow** too, with the new addresses.
- Redeploying **GrantEscrow** abandons every grant held by the old one. There is
  no migration path and no admin key to build one with. Drain live grants before
  replacing an escrow that holds money.

Update `VITE_ESCROW_ADDRESS` (and the others) and rebuild the frontend after any
redeploy. The old address does not fail loudly; it just serves stale state.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Contract Queues not found`, `IdlenessPhase not found` | Missing or wrong version pragma on line 1. Copy the header from Studio's current default template. |
| `Could not load contract schema` | A storage type the schema generator cannot describe. Check every custom struct is `@allow_storage @dataclass`, every `TreeMap` is keyed by `str`, and no field is a bare `int`. |
| `AssertionError: TreeMap <- TreeMap` on a finalized tx | A `TreeMap` was assigned in `__init__`. The GenVM creates them; leave them alone. |
| `AttributeError: module 'genlayer' has no attribute 'Contract'` | Someone wrote `import genlayer` instead of `from genlayer import *`. The star import is what injects the configured `gl`. |
| Sidebar says "not deployed" but the tx is FINALIZED | Click the transaction and read `Result`. Finalized is not success. |
| Deploy worked yesterday, fails today | Settings → Reset Storage → Confirm → hard refresh. |
| The app loads but every write fails | Almost never the contract. Is the *connected* account funded *on Studionet*? |
| `An unknown RPC error occurred. Details: 'from'` | The wallet is on another chain. The app requests the switch on connect; approve it. |
