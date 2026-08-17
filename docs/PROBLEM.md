# The problem GrantMilestoneEscrow solves

## Today

A DAO or foundation awards a grant. The grant document says something like:

> **Milestone 2 — $12,000.** Ship v0.2 with wallet authentication, a public
> demo deployment, and automated test coverage over the auth module.

Three months later the builder says "done". Now somebody has to decide whether
that sentence is true.

In practice that decision costs a committee call, a reviewer who skims a repo
at 11pm, and two weeks of wall clock. The reviewer is usually one person. That
person may be friendly with the builder, may be tired, may not read the diff.
Nobody can audit how the call was made, and the builder has no recourse other
than complaining in Discord.

The failure modes are well known to anyone who has run a grants program:

- **Reviewer capture.** The person releasing the money knows the person
  receiving it.
- **Moving goalposts.** The acceptance criteria drift after the work starts,
  because they were never pinned to anything.
- **Evidence theatre.** A release tag is created, a demo link is posted, and
  nobody checks that the tag actually contains the work or predates the grant.
- **No appeal.** A "no" is final because there is no second forum.
- **No history.** Next year's committee cannot see how last year's calls were
  made, so standards drift.

## Why a normal smart contract cannot fix it

Solidity can hold the money and can check that a transaction happened. It
cannot read *"ship v0.2 with wallet authentication"* and decide whether a
GitHub release satisfies it. That decision is a judgment about natural language
measured against unstructured evidence.

The usual workaround is an oracle: some off-chain service calls an LLM and
writes a verdict on-chain. That just moves the trusted party. Whoever runs the
oracle now decides who gets paid, and the chain records their answer without
being able to question it.

## What GenLayer changes

GenLayer puts the judgment *inside* consensus. Every validator independently:

1. Fetches the same three evidence sources over the public internet — no
   oracle, no relayer, no indexer.
2. Runs its own LLM over the milestone's pinned acceptance criteria and the
   fetched evidence.
3. Derives a **payout tier** from its own reading.
4. Votes.

The contract only releases money when independent validators, running
different models, land on the *same payout tier*. Disagreement is not papered
over — it blocks the release and forces a clarified resubmission.

That is the whole product. Remove the LLM and the on-chain web access and there
is nothing left: no verdict, no payout, no dispute forum.

## The one-line pitch

> A grant escrow that pays out only when independent AI validators — each
> reading the public evidence themselves — agree on how complete the work is.
> Without GenLayer there is no jury, only an oracle you have to trust.
