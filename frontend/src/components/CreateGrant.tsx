import { useEffect, useState } from 'react';
import { createGrant, explainError, listPolicies, type WriteProgress } from '../lib/client';
import { formatGen, normalizeRepo, parseGen } from '../lib/format';
import type { MilestoneDraft, Policy } from '../lib/types';
import { ConsensusProgress } from './ConsensusProgress';

const REPO_SLUG_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;

const BLANK: MilestoneDraft = {
  title: '',
  allocationGen: '',
  criteria: ['', ''],
};

interface CreateGrantProps {
  account: `0x${string}` | null;
  onCreated: (grantId: string) => void;
}

export function CreateGrant({ account, onCreated }: CreateGrantProps) {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [policyId, setPolicyId] = useState('');
  const [grantee, setGrantee] = useState('');
  // Prefill the builder address with the connected wallet the first time it
  // becomes known. Reviewers most often want to fund a demo grant to
  // themselves so they can submit evidence on the next screen, and this saves
  // a copy-paste while still allowing them to overwrite for a real grant.
  const [granteeAutoFilled, setGranteeAutoFilled] = useState(false);
  useEffect(() => {
    if (account && !granteeAutoFilled && grantee === '') {
      setGrantee(account);
      setGranteeAutoFilled(true);
    }
  }, [account, grantee, granteeAutoFilled]);
  const [repo, setRepo] = useState('');
  const [title, setTitle] = useState('');
  const [durationDays, setDurationDays] = useState('180');
  const [milestones, setMilestones] = useState<MilestoneDraft[]>([{ ...BLANK }]);
  const [progress, setProgress] = useState<WriteProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPolicies()
      .then((page) => {
        setPolicies(page.items);
        if (page.items.length) setPolicyId(page.items[0].policy_id);
      })
      .catch((caught) => setError(explainError(caught)));
  }, []);

  function patch(index: number, next: Partial<MilestoneDraft>) {
    setMilestones((current) =>
      current.map((draft, i) => (i === index ? { ...draft, ...next } : draft)),
    );
  }

  let deposit: bigint | null = null;
  let depositError: string | null = null;
  try {
    deposit = milestones.reduce(
      (total, draft) => total + (draft.allocationGen ? parseGen(draft.allocationGen) : 0n),
      0n,
    );
  } catch (caught) {
    depositError = (caught as Error).message;
  }

  /**
   * What is still missing, stated plainly.
   *
   * A disabled button with no explanation is a dead end: the form looks
   * complete, the deposit total is right there, and nothing says which field is
   * holding it up. Every condition the contract enforces is listed here instead,
   * so the answer is on screen rather than in a revert message.
   */
  const normalizedRepo = normalizeRepo(repo);
  const repoLooksValid = REPO_SLUG_RE.test(normalizedRepo);

  const blockers: string[] = [];
  if (title.trim() === '') blockers.push('Give the grant a title.');
  if (repo.trim() === '') {
    blockers.push('Name the GitHub repository, as owner/name.');
  } else if (!repoLooksValid) {
    blockers.push(
      `Repository must be a GitHub owner/name (paste the URL or type the slug). "${normalizedRepo || repo.trim()}" is not one.`,
    );
  }
  if (!/^0x[0-9a-fA-F]{40}$/.test(grantee.trim())) {
    blockers.push('Enter the builder\'s address — 0x followed by 40 hex characters.');
  }
  if (policyId === '') {
    blockers.push(
      policies.length === 0
        ? 'No review policy could be read from the policy contract. Publish one before funding a grant.'
        : 'Choose a review policy.',
    );
  }
  milestones.forEach((draft, index) => {
    const label = `Milestone ${index + 1}`;
    if (draft.title.trim() === '') blockers.push(`${label}: add a title.`);
    if (draft.allocationGen.trim() === '') blockers.push(`${label}: set an allocation in GEN.`);
    const usable = draft.criteria.filter((c) => c.trim().length >= 8);
    if (usable.length < 2) {
      blockers.push(
        `${label}: needs at least 2 acceptance criteria of 8 characters or more (${usable.length} so far).`,
      );
    }
    const folded = usable.map((c) => c.trim().toLowerCase());
    if (new Set(folded).size !== folded.length) {
      blockers.push(`${label}: two criteria are the same. Each must be distinct.`);
    }
  });
  if (deposit !== null && deposit === 0n) blockers.push('The total deposit cannot be zero.');

  const ready = blockers.length === 0 && depositError === null && deposit !== null && deposit > 0n;

  async function submit() {
    setError(null);
    try {
      const payload = milestones.map((draft) => ({
        title: draft.title.trim(),
        allocation: parseGen(draft.allocationGen).toString(),
        criteria: draft.criteria.map((c) => c.trim()).filter((c) => c.length >= 8),
      }));

      const hash = await createGrant({
        grantee: grantee.trim(),
        repo: normalizedRepo,
        title: title.trim(),
        policyId,
        milestonesJson: JSON.stringify(payload),
        durationDays: Number(durationDays),
        deposit: deposit!,
        onProgress: setProgress,
      });
      onCreated(hash);
    } catch (caught) {
      setError(explainError(caught));
    } finally {
      setProgress(null);
    }
  }

  const activePolicy = policies.find((p) => p.policy_id === policyId);

  return (
    <div className="create">
      <h2>Fund a grant</h2>
      <p className="lead">
        Your deposit is held by the contract and split across the milestones below. The acceptance
        criteria you write here are frozen on chain — they are the exact sentences validators will
        judge against, and neither side can edit them afterwards.
      </p>

      <section className="panel">
        <div className="field-row">
          <label>
            Grant title
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Widget platform grant" />
          </label>
          <label>
            GitHub repository
            <input
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder="acme/widget or https://github.com/acme/widget"
            />
            {repo.trim() !== '' && (
              <span className={`small ${repoLooksValid ? 'muted' : 'error'}`}>
                {repoLooksValid
                  ? `Will be stored as ${normalizedRepo}`
                  : 'A GitHub URL, an owner/name slug, or a git@github.com clone URL.'}
              </span>
            )}
          </label>
        </div>
        <div className="field-row">
          <label>
            Builder address
            <input value={grantee} onChange={(e) => setGrantee(e.target.value)} placeholder="0x…" />
            {account && (
              <button
                type="button"
                className="ghost inline"
                onClick={() => setGrantee(account)}
                disabled={grantee.toLowerCase() === account}
              >
                {grantee.toLowerCase() === account
                  ? 'Using your connected wallet'
                  : 'Use my connected wallet'}
              </button>
            )}
          </label>
          <label>
            Deadline (days)
            <input
              value={durationDays}
              onChange={(e) => setDurationDays(e.target.value.replace(/\D/g, ''))}
              inputMode="numeric"
            />
          </label>
        </div>
        <label>
          Review policy
          <select value={policyId} onChange={(e) => setPolicyId(e.target.value)}>
            {policies.map((policy) => (
              <option key={policy.policy_id} value={policy.policy_id}>
                {policy.policy_id} — {policy.label}
              </option>
            ))}
          </select>
        </label>
        {activePolicy && (
          <p className="small muted">
            Under this policy, {Number(activePolicy.substantial_permille) / 10}% of requirements met
            releases {Number(activePolicy.substantial_payout_bps) / 100}%, and{' '}
            {Number(activePolicy.partial_permille) / 10}% releases{' '}
            {Number(activePolicy.partial_payout_bps) / 100}%. A jury less than{' '}
            {activePolicy.confidence_threshold}% sure returns nothing and asks for a clearer
            submission.
          </p>
        )}
      </section>

      {milestones.map((draft, index) => (
        <section key={index} className="panel">
          <div className="panel-head">
            <h4>Milestone {index + 1}</h4>
            {milestones.length > 1 && (
              <button
                className="ghost"
                onClick={() => setMilestones((current) => current.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            )}
          </div>
          <div className="field-row">
            <label>
              Title
              <input
                value={draft.title}
                onChange={(e) => patch(index, { title: e.target.value })}
                placeholder="Ship v0.2 with wallet auth"
              />
            </label>
            <label>
              Allocation (GEN)
              <input
                value={draft.allocationGen}
                onChange={(e) => patch(index, { allocationGen: e.target.value })}
                placeholder="12"
                inputMode="decimal"
              />
            </label>
          </div>

          <fieldset className="criteria-editor">
            <legend>Acceptance criteria (2–12, each distinct)</legend>
            <p className="small muted">
              Write one checkable thing per line. Vague criteria produce low-confidence juries,
              which stall rather than pay.
            </p>
            {draft.criteria.map((criterion, ci) => (
              <input
                key={ci}
                value={criterion}
                onChange={(e) =>
                  patch(index, {
                    criteria: draft.criteria.map((c, i) => (i === ci ? e.target.value : c)),
                  })
                }
                placeholder={`R${ci + 1} — e.g. wallet sign-in works on the deployed demo`}
              />
            ))}
            <button
              className="ghost"
              disabled={draft.criteria.length >= 12}
              onClick={() => patch(index, { criteria: [...draft.criteria, ''] })}
            >
              Add criterion
            </button>
          </fieldset>
        </section>
      ))}

      <button
        className="ghost"
        disabled={milestones.length >= 12}
        onClick={() => setMilestones((current) => [...current, { ...BLANK }])}
      >
        Add milestone
      </button>

      <section className="panel summary">
        <div>
          <span className="label">Total deposit</span>
          <strong>{depositError ? '—' : `${formatGen(deposit ?? 0n)} GEN`}</strong>
        </div>
        <p className="small muted">
          The deposit must equal the sum of the allocations exactly. An unallocated remainder is
          money the contract has no rule for, so it refuses the grant rather than holding it.
        </p>
        <button className="primary" disabled={!ready || progress !== null} onClick={submit}>
          Fund grant
        </button>

        {blockers.length > 0 && (
          <ul className="blockers">
            {blockers.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </section>

      <ConsensusProgress progress={progress} />
      {(error || depositError) && <p className="error">{error ?? depositError}</p>}
    </div>
  );
}
