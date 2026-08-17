import { useEffect, useState } from 'react';
import { createGrant, explainError, listPolicies, type WriteProgress } from '../lib/client';
import { formatGen, parseGen } from '../lib/format';
import type { MilestoneDraft, Policy } from '../lib/types';
import { ConsensusProgress } from './ConsensusProgress';

const BLANK: MilestoneDraft = {
  title: '',
  allocationGen: '',
  criteria: ['', ''],
};

export function CreateGrant({ onCreated }: { onCreated: (grantId: string) => void }) {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [policyId, setPolicyId] = useState('');
  const [grantee, setGrantee] = useState('');
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

  const ready =
    deposit !== null &&
    deposit > 0n &&
    grantee.trim() !== '' &&
    repo.trim() !== '' &&
    title.trim() !== '' &&
    policyId !== '' &&
    milestones.every(
      (draft) =>
        draft.title.trim() !== '' &&
        draft.allocationGen.trim() !== '' &&
        draft.criteria.filter((c) => c.trim().length >= 8).length >= 2,
    );

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
        repo: repo.trim(),
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
            <input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="acme/widget" />
          </label>
        </div>
        <div className="field-row">
          <label>
            Builder address
            <input value={grantee} onChange={(e) => setGrantee(e.target.value)} placeholder="0x…" />
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
      </section>

      <ConsensusProgress progress={progress} />
      {(error || depositError) && <p className="error">{error ?? depositError}</p>}
    </div>
  );
}
