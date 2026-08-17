import type { WriteProgress } from '../lib/client';
import { explorerTx } from '../lib/config';

/**
 * Narrates a pending write.
 *
 * A review transaction is not slow because the network is congested. It is slow
 * because every validator is independently fetching three GitHub endpoints,
 * rendering a page, and running a model over it. Saying so turns a wait that
 * looks broken into a wait that looks like the product working.
 */

const COPY: Record<WriteProgress['phase'], { title: string; detail: string }> = {
  validating: {
    title: 'Checking your input',
    detail: 'Making sure the transaction will not be rejected before you sign it.',
  },
  'awaiting-signature': {
    title: 'Waiting for your signature',
    detail: 'Approve the transaction in your wallet.',
  },
  submitted: {
    title: 'Submitted',
    detail: 'The transaction is on its way to the validators.',
  },
  'awaiting-consensus': {
    title: 'The jury is reading the evidence',
    detail:
      'Each validator is fetching the release, the tag, the commit and your deliverable page, then judging the acceptance criteria with its own model. They have to land on the same payout tier before anything is released, so this takes longer than an ordinary transaction.',
  },
  finalized: {
    title: 'Finalized',
    detail: 'The validators agreed and the result is on chain.',
  },
};

const ORDER: WriteProgress['phase'][] = [
  'validating',
  'awaiting-signature',
  'submitted',
  'awaiting-consensus',
  'finalized',
];

export function ConsensusProgress({ progress }: { progress: WriteProgress | null }) {
  if (!progress) return null;
  const copy = COPY[progress.phase];
  const currentIndex = ORDER.indexOf(progress.phase);
  const link = explorerTx(progress.hash);

  return (
    <div className={`progress progress-${progress.phase}`} role="status" aria-live="polite">
      <ol className="progress-steps">
        {ORDER.map((phase, index) => (
          <li
            key={phase}
            className={
              index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'pending'
            }
            aria-current={index === currentIndex ? 'step' : undefined}
          />
        ))}
      </ol>
      <div className="progress-body">
        <strong>{copy.title}</strong>
        <p>{copy.detail}</p>
        {link && (
          <a href={link} target="_blank" rel="noreferrer noopener" className="mono small">
            View transaction on the explorer ↗
          </a>
        )}
      </div>
    </div>
  );
}
