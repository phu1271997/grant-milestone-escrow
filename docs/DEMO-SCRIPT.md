# Demo script

Target length: three minutes. The whole point is the moment where money moves
because validators agreed, so get there fast and let that part breathe.

## Before you record

- [ ] Three contracts deployed to Studionet, `scripts/verify-deployment.mjs` all green
- [ ] `standard-v1` policy published
- [ ] **Two** MetaMask accounts, both funded with GEN **on Studionet**: a sponsor
      and a builder. Switching between them on camera is what makes it obvious
      nobody is reviewing their own work.
- [ ] A real GitHub repository you control, with a release tag whose notes
      describe the work, published *after* you fund the grant. The contract
      blocks a release that predates its grant, so fund first, then tag.
- [ ] A deliverable page that loads (a Vercel preview is fine)
- [ ] Frontend deployed, `.env.local` filled in, wallet on Studionet

---

## 0:00 — The problem, in one breath

> "A DAO says: twelve thousand dollars when you ship v0.2 with wallet auth, a
> public demo, and tests on the auth module. Three months later the builder says
> done. Somebody has to decide whether that sentence is true — and today that
> somebody is one tired reviewer who knows the builder."

## 0:20 — Fund a grant

Sponsor account. Fill in the form. **Slow down on the acceptance criteria.**

> "These three sentences get frozen on chain. Not a hash of them — the sentences
> themselves, because they're what the validators will read. Neither side can
> edit them after this."

Sign. Show the deposit landing in escrow.

## 0:50 — Submit evidence

Switch to the builder account — say that you are switching.

Enter the release tag and the demo URL. Submit.

> "That's all the builder does. No form to fill in about what was done, no
> screenshots. Just: here's the tag, here's the deployed thing."

## 1:15 — Convene the jury

> "Anyone can start the review. The caller has no influence on the result — so
> there's nobody to wait for."

Click **Review this milestone**. Sign.

**Let the progress panel sit on screen and read it aloud.**

> "This is slower than an ordinary transaction, and the reason is the product.
> Every validator is independently hitting three GitHub endpoints — the release,
> the tag, the commit — rendering the demo page, and running its own model over
> those three criteria. Not one server doing this. All of them, separately."

## 1:45 — The verdict

The tier appears. Money moves.

Scroll to the review record and point at the numbers:

> "Six of eight requirements met, jury 84% confident, commit `a91f3c07b2`. And
> here's the part that matters — the validators had to agree on the *tier* and
> on *which commit they read*. They did **not** have to agree on this count or
> this confidence number."
>
> "So two validators can disagree about requirement three and still settle,
> because both readings land in the same band. But if one says complete and
> another says partial — a quarter of the milestone — the transaction just
> fails. Nothing pays out on a split jury."

If you have time, show `tests/test_consensus.py` for two seconds. It is the
cheapest credibility in the demo.

## 2:20 — Appeal

Builder account. Open the appeal panel.

> "A no isn't final. Post a bond, say what the first review missed, point at
> evidence. If the second jury raises the tier you get the bond back and the
> difference. If it doesn't, the bond goes back into the grant — to the sponsor,
> not to anyone's pocket. And if that jury can't read the evidence either, you
> get the bond back and keep the appeal. You don't pay for the network being
> down."

## 2:45 — The close

> "Take the AI out and there's no product. Not a worse product — no product.
> There's no verdict, no forum, nothing to release the money against."
>
> "Take GenLayer out specifically and you get an oracle: one server calling a
> model, deciding who gets paid, and the chain writing down its answer without
> being able to question it. That's the same tired reviewer with extra steps."
>
> "Here the judgment happens *inside* consensus. Nobody runs the jury."

---

## Do not

- Do not say "testnet". This is Studionet. Saying otherwise is wrong and free to
  get right.
- Do not cut the consensus wait. It is the demo.
- Do not use one wallet for both sides. The whole pitch is that nobody approves
  their own work.
- Do not hide a `NEEDS_CLARIFICATION` if you get one on camera. Explain it —
  "the jury wasn't sure enough, so nothing paid and nothing counts against the
  builder" is a *better* moment than a clean pass, because it shows the system
  declining to guess with someone's money.
