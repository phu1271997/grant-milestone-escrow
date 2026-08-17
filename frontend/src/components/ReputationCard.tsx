import { formatGen, shortAddress } from '../lib/format';
import type { Reputation } from '../lib/types';

/**
 * A builder's track record, read from the separate reputation ledger.
 *
 * Clarifications are shown apart from rejections because they mean different
 * things: a clarification is the jury saying it could not read the evidence,
 * which is not a judgment on the work.
 */
export function ReputationCard({ reputation }: { reputation: Reputation }) {
  if (!reputation.known) {
    return (
      <section className="reputation empty">
        <h4>Builder track record</h4>
        <p className="small muted">
          No settled milestones yet for {shortAddress(reputation.builder)}. This will fill in as
          the escrow records outcomes.
        </p>
      </section>
    );
  }

  const stats: Array<[string, string]> = [
    ['Milestones settled', reputation.settlements],
    ['Complete', reputation.complete],
    ['Substantial', reputation.substantial],
    ['Partial', reputation.partial],
    ['Insufficient', reputation.insufficient],
    ['Rejected', reputation.rejected],
    ['Clarifications', reputation.clarifications],
    ['Appeals upheld', `${reputation.appeals_upheld} of ${reputation.appeals_filed}`],
  ];

  return (
    <section className="reputation">
      <h4>
        Builder track record <span className="mono small">{shortAddress(reputation.builder)}</span>
      </h4>
      <div className="reputation-grid">
        {stats.map(([label, value]) => (
          <div key={label}>
            <span className="label">{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
        <div>
          <span className="label">Total released</span>
          <strong>{formatGen(reputation.total_paid)} GEN</strong>
        </div>
      </div>
    </section>
  );
}
