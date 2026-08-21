import { useCallback, useEffect, useState } from 'react';
import { closeGrant, explainError, getGrant, getReputation, type WriteProgress } from '../lib/client';
import { explorerAddress } from '../lib/config';
import { formatDate, formatGen, shortAddress } from '../lib/format';
import type { Grant, Milestone, Reputation } from '../lib/types';
import { ConsensusProgress } from './ConsensusProgress';
import { MilestoneCard } from './MilestoneCard';
import { ReputationCard } from './ReputationCard';

interface Props {
  grantId: string;
  account: `0x${string}` | null;
}

export function GrantDetail({ grantId, account }: Props) {
  const [grant, setGrant] = useState<Grant | null>(null);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [reputation, setReputation] = useState<Reputation | null>(null);
  const [progress, setProgress] = useState<WriteProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await getGrant(grantId);
      setGrant(result.grant);
      setMilestones(result.milestones);
      setReputation(await getReputation(result.grant.grantee).catch(() => null));
      setError(null);
    } catch (caught) {
      setError(explainError(caught));
    } finally {
      setLoading(false);
    }
  }, [grantId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="muted">Reading the registry…</p>;
  if (error && !grant) return <p className="error">{error}</p>;
  if (!grant) return null;

  const isSponsor = account !== null && account === grant.sponsor.toLowerCase();
  const isBuilder = account !== null && account === grant.grantee.toLowerCase();
  const closed = grant.status === '1';
  const repoUrl = `https://github.com/${grant.repo}`;

  let roleLabel: string;
  let roleHint: string;
  if (account === null) {
    roleLabel = 'Not connected';
    roleHint =
      'Browsing is read-only. Connect the builder wallet to submit evidence, the sponsor wallet to close the grant, or any wallet to convene the jury and pay gas.';
  } else if (isBuilder && isSponsor) {
    roleLabel = 'You are the sponsor and the builder';
    roleHint = 'You can fund, submit, review and close this grant.';
  } else if (isBuilder) {
    roleLabel = 'You are the builder';
    roleHint = 'You can submit each milestone for review, and file one appeal per milestone.';
  } else if (isSponsor) {
    roleLabel = 'You are the sponsor';
    roleHint =
      'You can close the grant once every milestone is settled or the deadline passes. Only the builder wallet can submit evidence.';
  } else {
    roleLabel = 'You are an observer';
    roleHint = `Only the builder (${grant.grantee}) can submit milestone evidence for this grant. To try submitting evidence end-to-end, fund a new grant with your own wallet as the builder — the "New grant" tab prefills your address for exactly this reason.`;
  }

  return (
    <div className="detail">
      <section className="detail-head">
        <div>
          <h2>{grant.title}</h2>
          <p className="small muted">
            Grant #{grant.grant_id} · funded {formatDate(grant.created_at)} · deadline{' '}
            {formatDate(grant.deadline_at)} · policy <code>{grant.policy_id}</code>
          </p>
        </div>
        <div className="detail-money">
          <div>
            <span className="label">Released</span>
            <strong>{formatGen(grant.released)} GEN</strong>
          </div>
          <div>
            <span className="label">Still escrowed</span>
            <strong>{formatGen(grant.escrowed)} GEN</strong>
          </div>
        </div>
      </section>

      <dl className="facts wide">
        <div>
          <dt>Repository</dt>
          <dd>
            <a href={repoUrl} target="_blank" rel="noreferrer noopener">
              {grant.repo} ↗
            </a>
          </dd>
        </div>
        <div>
          <dt>Sponsor</dt>
          <dd className="mono">
            <a href={explorerAddress(grant.sponsor) ?? repoUrl} target="_blank" rel="noreferrer noopener">
              {shortAddress(grant.sponsor)}
            </a>
          </dd>
        </div>
        <div>
          <dt>Builder</dt>
          <dd className="mono">
            <a href={explorerAddress(grant.grantee) ?? repoUrl} target="_blank" rel="noreferrer noopener">
              {shortAddress(grant.grantee)}
            </a>
          </dd>
        </div>
        <div>
          <dt>Milestones settled</dt>
          <dd>
            {grant.settled_count} of {grant.milestone_count}
          </dd>
        </div>
      </dl>

      {reputation && <ReputationCard reputation={reputation} />}

      <section className={`role-banner ${isBuilder ? 'is-builder' : isSponsor ? 'is-sponsor' : 'is-observer'}`}>
        <strong>{roleLabel}</strong>
        <p className="small muted">{roleHint}</p>
        {!isBuilder && !isSponsor && (
          <a className="ghost inline" href="#/new">
            Fund a grant to yourself →
          </a>
        )}
      </section>

      <section>
        <h3>Milestones</h3>
        {milestones.map((milestone) => (
          <MilestoneCard
            key={milestone.index}
            grant={grant}
            milestone={milestone}
            account={account}
            onChanged={load}
          />
        ))}
      </section>

      {isSponsor && !closed && (
        <section className="panel">
          <h4>Close the grant</h4>
          <p className="small muted">
            Returns whatever is still escrowed. Available once every milestone has reached a
            terminal state, or once the deadline has passed — so a builder who never submits
            cannot strand your deposit indefinitely.
          </p>
          <button
            disabled={progress !== null}
            onClick={async () => {
              setError(null);
              try {
                await closeGrant({ grantId: grant.grant_id, onProgress: setProgress });
                await load();
              } catch (caught) {
                setError(explainError(caught));
              } finally {
                setProgress(null);
              }
            }}
          >
            Close and refund {formatGen(grant.escrowed)} GEN
          </button>
          <ConsensusProgress progress={progress} />
        </section>
      )}

      {closed && <p className="muted">This grant is closed. Its records remain readable.</p>}
      {error && grant && <p className="error">{error}</p>}
    </div>
  );
}
