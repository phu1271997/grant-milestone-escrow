import { formatDate, formatGen, percentFromBps, shortAddress, shortSha, TIER_COPY } from '../lib/format';
import { OBSERVATION_LABELS, type Review } from '../lib/types';

/**
 * The audit trail for one milestone.
 *
 * Showing *why* is the point of the product, so the reasoning gets as much room
 * as the verdict: which observations the jury made, how sure it was, and which
 * exact commit it read. The distinction between what validators had to agree on
 * (the tier) and what they did not (counts, confidence, individual findings) is
 * stated here rather than left for a reader to infer.
 */
export function ReviewTimeline({ reviews }: { reviews: Review[] }) {
  if (!reviews.length) {
    return <p className="muted">No review has been convened for this milestone yet.</p>;
  }

  return (
    <ol className="timeline">
      {reviews.map((review) => {
        const copy = TIER_COPY[review.tier];
        const observations = [...review.blockers, ...review.gaps];
        return (
          <li key={review.review_id} className="timeline-item">
            <div className="timeline-head">
              <span className={`tier-badge ${copy.tone}`}>{copy.label}</span>
              <span className="small muted">
                {review.kind === '1' ? 'Appeal review' : 'Initial review'} ·{' '}
                {formatDate(review.created_at)}
              </span>
            </div>

            <p className="tier-blurb">{copy.blurb}</p>

            <dl className="facts">
              <div>
                <dt>Requirements met</dt>
                <dd>
                  {review.met_count} of {review.total_count}
                </dd>
              </div>
              <div>
                <dt>Released</dt>
                <dd>
                  {percentFromBps(review.payout_bps)}
                  {review.paid_amount !== '0' && ` · ${formatGen(review.paid_amount)} GEN`}
                </dd>
              </div>
              <div>
                <dt>Jury confidence</dt>
                <dd>{review.confidence}%</dd>
              </div>
              <div>
                <dt>Commit read</dt>
                <dd className="mono">{shortSha(review.commit_sha) || '—'}</dd>
              </div>
              <div>
                <dt>Evidence fingerprint</dt>
                <dd className="mono">{shortSha(review.evidence_fingerprint)}</dd>
              </div>
              <div>
                <dt>Convened by</dt>
                <dd className="mono">{shortAddress(review.reviewer)}</dd>
              </div>
            </dl>

            {observations.length > 0 && (
              <ul className="observations">
                {observations.map((key) => (
                  <li key={key}>
                    <code>{key}</code>
                    <span>{OBSERVATION_LABELS[key] ?? 'Unrecognised observation.'}</span>
                  </li>
                ))}
              </ul>
            )}

            <p className="small muted consensus-note">
              Validators had to agree on the tier and on the commit read. They did not have to
              agree on the requirement counts or the confidence shown above — those are one
              validator's reasoning, recorded so you can see it.
            </p>
          </li>
        );
      })}
    </ol>
  );
}
