import { useEffect, useState } from 'react';
import {
  fileAppeal,
  getAppealQuote,
  getReviews,
  reviewMilestone,
  submitMilestone,
  explainError,
  type WriteProgress,
} from '../lib/client';
import { formatGen, percentFromBps, TIER_COPY } from '../lib/format';
import { MilestoneState, type AppealQuote, type Grant, type Milestone, type Review } from '../lib/types';
import { ConsensusProgress } from './ConsensusProgress';
import { ReviewTimeline } from './ReviewTimeline';

interface Props {
  grant: Grant;
  milestone: Milestone;
  account: `0x${string}` | null;
  onChanged: () => void;
}

export function MilestoneCard({ grant, milestone, account, onChanged }: Props) {
  const index = Number(milestone.index);
  const isGrantee = account !== null && account === grant.grantee.toLowerCase();
  const state = milestone.state;

  const [reviews, setReviews] = useState<Review[]>([]);
  const [quote, setQuote] = useState<AppealQuote | null>(null);
  const [progress, setProgress] = useState<WriteProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Auto-expand Open and Submitted milestones so the submit affordance is
  // visible without a click. Final/Settled milestones default to expanded too —
  // a reviewer scanning the page needs to see the verdict and history without
  // hunting for a disclosure triangle. Collapse remains available on the head.
  const [expanded, setExpanded] = useState(true);

  const [tag, setTag] = useState(milestone.release_tag);
  const [evidenceUrl, setEvidenceUrl] = useState(milestone.evidence_url);
  const [rebuttal, setRebuttal] = useState('');
  const [extraUrl, setExtraUrl] = useState('');
  const [showAppeal, setShowAppeal] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getReviews(grant.grant_id, index)
      .then((page) => !cancelled && setReviews(page.items))
      .catch(() => undefined);
    getAppealQuote(grant.grant_id, index)
      .then((result) => !cancelled && setQuote(result))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [grant.grant_id, index, milestone.review_count, milestone.settled_tier]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      onChanged();
    } catch (caught) {
      setError(explainError(caught));
    } finally {
      setProgress(null);
    }
  }

  const tier = milestone.settled_tier ? TIER_COPY[milestone.settled_tier] : null;

  return (
    <article className="milestone">
      <button className="milestone-head" onClick={() => setExpanded((open) => !open)}>
        <span className="milestone-index">M{index + 1}</span>
        <span className="milestone-title">{milestone.title}</span>
        <span className="milestone-amount">{formatGen(milestone.allocation)} GEN</span>
        {tier ? (
          <span className={`tier-badge ${tier.tone}`}>
            {tier.label} · {percentFromBps(milestone.settled_payout_bps)}
          </span>
        ) : (
          <span className="tier-badge tone-pending">
            {state === MilestoneState.Submitted ? 'Awaiting review' : 'Open'}
          </span>
        )}
      </button>

      {expanded && (
        <div className="milestone-body">
          <section>
            <h4>Acceptance criteria</h4>
            <p className="small muted">
              Frozen when the grant was funded. These are the exact sentences the jury is asked
              to judge against — they cannot be edited afterwards.
            </p>
            <ol className="criteria">
              {milestone.criteria.map((text, i) => (
                <li key={i}>
                  <code>{milestone.requirement_ids[i]}</code>
                  <span>{text}</span>
                </li>
              ))}
            </ol>
          </section>

          {(state === MilestoneState.Open || state === MilestoneState.Submitted) && (
            <section className="panel">
              <h4>Submit evidence</h4>
              <p className="small muted">
                The release tag must exist in <code>{grant.repo}</code>. The deliverable page is
                optional but gives the jury something to check the release notes against.
              </p>
              {!isGrantee && (
                <p className="small role-hint">
                  {account === null
                    ? 'Connect the builder wallet to submit.'
                    : 'Only the builder wallet can submit. Switch MetaMask to '}
                  <code>{grant.grantee}</code>
                  {account !== null && ' to enable this form.'}
                </p>
              )}
              <div className="field-row">
                <label>
                  Release tag
                  <input
                    value={tag}
                    onChange={(event) => setTag(event.target.value)}
                    placeholder="v0.2.0"
                    disabled={!isGrantee}
                  />
                </label>
                <label>
                  Deliverable URL
                  <input
                    value={evidenceUrl}
                    onChange={(event) => setEvidenceUrl(event.target.value)}
                    placeholder="https://demo.example/app"
                    disabled={!isGrantee}
                  />
                </label>
              </div>
              <button
                className="primary"
                disabled={!isGrantee || progress !== null || tag.trim() === ''}
                onClick={() =>
                  run(() =>
                    submitMilestone({
                      grantId: grant.grant_id,
                      milestoneIndex: index,
                      releaseTag: tag.trim(),
                      evidenceUrl: evidenceUrl.trim(),
                      onProgress: setProgress,
                    }),
                  )
                }
              >
                {state === MilestoneState.Submitted ? 'Replace evidence' : 'Submit for review'}
              </button>
            </section>
          )}

          {state === MilestoneState.Submitted && (
            <section className="panel accent">
              <h4>Convene the jury</h4>
              <p className="small">
                Anyone can start a review. The caller has no influence on the result, so there is
                no reviewer to wait on.
              </p>
              <button
                className="primary"
                disabled={progress !== null}
                onClick={() =>
                  run(() =>
                    reviewMilestone({
                      grantId: grant.grant_id,
                      milestoneIndex: index,
                      onProgress: setProgress,
                    }),
                  )
                }
              >
                Review this milestone
              </button>
            </section>
          )}

          {isGrantee && quote?.appealable && (
            <section className="panel">
              <h4>Appeal</h4>
              <p className="small muted">
                A bond of <strong>{formatGen(quote.required_bond)} GEN</strong> is required, and
                must match exactly. It comes back if the second jury raises the tier, and also if
                that jury simply cannot read the evidence. It is forfeited to the grant balance
                otherwise. One appeal per milestone.
              </p>
              {showAppeal ? (
                <>
                  <label>
                    Your response
                    <textarea
                      rows={4}
                      value={rebuttal}
                      onChange={(event) => setRebuttal(event.target.value)}
                      placeholder="Point at concrete evidence the first review missed."
                    />
                  </label>
                  <label>
                    Additional evidence URL (optional)
                    <input
                      value={extraUrl}
                      onChange={(event) => setExtraUrl(event.target.value)}
                      placeholder="https://staging.example/feature"
                    />
                  </label>
                  <button
                    className="primary"
                    disabled={progress !== null || rebuttal.trim().length < 20}
                    onClick={() =>
                      run(() =>
                        fileAppeal({
                          grantId: grant.grant_id,
                          milestoneIndex: index,
                          rebuttal: rebuttal.trim(),
                          extraEvidenceUrl: extraUrl.trim(),
                          bond: BigInt(quote.required_bond),
                          onProgress: setProgress,
                        }),
                      )
                    }
                  >
                    Post bond and appeal
                  </button>
                </>
              ) : (
                <button onClick={() => setShowAppeal(true)}>Contest this result</button>
              )}
            </section>
          )}

          <ConsensusProgress progress={progress} />
          {error && <p className="error">{error}</p>}

          <section>
            <h4>Review history</h4>
            <ReviewTimeline reviews={reviews} />
          </section>
        </div>
      )}
    </article>
  );
}
