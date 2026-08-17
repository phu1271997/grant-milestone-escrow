import { useEffect, useState } from 'react';
import { explainError, listGrants } from '../lib/client';
import { formatDate, formatGen, shortAddress } from '../lib/format';
import type { Grant } from '../lib/types';

export function GrantList({ onOpen }: { onOpen: (grantId: string) => void }) {
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listGrants()
      .then((page) => setGrants(page.items))
      .catch((caught) => setError(explainError(caught)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (grants === null) return <p className="muted">Reading the registry…</p>;

  if (!grants.length) {
    return (
      <div className="empty-state">
        <h2>No grants yet</h2>
        <p>
          Fund one to see the whole loop: pin the acceptance criteria, submit a release as
          evidence, and watch validators settle it without a committee.
        </p>
      </div>
    );
  }

  return (
    <div className="grant-list">
      {grants.map((grant) => {
        const progress =
          Number(grant.milestone_count) === 0
            ? 0
            : (Number(grant.settled_count) / Number(grant.milestone_count)) * 100;
        return (
          <button key={grant.grant_id} className="grant-row" onClick={() => onOpen(grant.grant_id)}>
            <div className="grant-row-main">
              <h3>{grant.title}</h3>
              <p className="small muted">
                <code>{grant.repo}</code> · builder {shortAddress(grant.grantee)} · funded{' '}
                {formatDate(grant.created_at)}
              </p>
            </div>
            <div className="grant-row-stats">
              <div>
                <span className="label">Deposit</span>
                <strong>{formatGen(grant.deposit)} GEN</strong>
              </div>
              <div>
                <span className="label">Released</span>
                <strong>{formatGen(grant.released)} GEN</strong>
              </div>
              <div className="grant-progress" aria-label={`${grant.settled_count} of ${grant.milestone_count} milestones settled`}>
                <div className="grant-progress-bar" style={{ width: `${progress}%` }} />
                <span className="small">
                  {grant.settled_count}/{grant.milestone_count} settled
                </span>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
