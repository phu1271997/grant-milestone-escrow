import { createClient } from 'genlayer-js';
import { chain, escrowAddress, policyAddress, reputationAddress } from './config';
import { connectWallet, ensureNetwork, getProvider } from './wallet';
import type {
  AppealQuote,
  Grant,
  Milestone,
  Page,
  Policy,
  Reputation,
  Review,
} from './types';

/**
 * The only place this app talks to the chain.
 *
 * Reads use a client with no account: the registry is public and browsing it
 * must never prompt a wallet. Writes build a client bound to the *address* of
 * the connected account, which makes MetaMask the signer — the SDK also accepts
 * a full account object and would then sign itself, which would mean holding a
 * key in the browser.
 */

const readClient = createClient({ chain });

function requireAddress(state: typeof escrowAddress, name: string): `0x${string}` {
  if (state.status !== 'ok') {
    throw new Error(
      `${name} is not configured. Set it in frontend/.env.local — see docs/DEPLOY-STUDIONET.md.`,
    );
  }
  return state.address;
}

async function readJson<T>(
  address: `0x${string}`,
  functionName: string,
  args: unknown[] = [],
): Promise<T> {
  const raw = await readClient.readContract({ address, functionName, args });
  if (typeof raw === 'string') return JSON.parse(raw) as T;
  return raw as T;
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export function listGrants(cursor = 0, limit = 25): Promise<Page<Grant>> {
  return readJson(requireAddress(escrowAddress, 'VITE_ESCROW_ADDRESS'), 'get_grants', [
    cursor,
    limit,
  ]);
}

export function getGrant(grantId: string): Promise<{ grant: Grant; milestones: Milestone[] }> {
  return readJson(requireAddress(escrowAddress, 'VITE_ESCROW_ADDRESS'), 'get_grant', [grantId]);
}

export function getReviews(
  grantId: string,
  milestoneIndex: number,
  cursor = 0,
  limit = 50,
): Promise<Page<Review>> {
  return readJson(requireAddress(escrowAddress, 'VITE_ESCROW_ADDRESS'), 'get_reviews', [
    grantId,
    milestoneIndex,
    cursor,
    limit,
  ]);
}

export function getAppealQuote(grantId: string, milestoneIndex: number): Promise<AppealQuote> {
  return readJson(requireAddress(escrowAddress, 'VITE_ESCROW_ADDRESS'), 'get_appeal_quote', [
    grantId,
    milestoneIndex,
  ]);
}

export function getReputation(builder: string): Promise<Reputation> {
  return readJson(
    requireAddress(reputationAddress, 'VITE_REPUTATION_ADDRESS'),
    'get_reputation',
    [builder],
  );
}

export function listPolicies(): Promise<Page<Policy>> {
  return readJson(requireAddress(policyAddress, 'VITE_POLICY_ADDRESS'), 'get_policies');
}

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

export type WritePhase =
  | 'validating'
  | 'awaiting-signature'
  | 'submitted'
  | 'awaiting-consensus'
  | 'finalized';

export interface WriteProgress {
  phase: WritePhase;
  hash?: `0x${string}`;
  note?: string;
}

interface WriteOptions {
  functionName: string;
  args: unknown[];
  value?: bigint;
  onProgress?: (progress: WriteProgress) => void;
}

/**
 * Send one write and wait for it to finalize.
 *
 * The phase callback exists because a non-deterministic transaction is slow in
 * a way users have no prior experience of: every validator is independently
 * fetching evidence and running a model. A spinner with no explanation reads as
 * a hang, so each phase is named as it happens.
 */
export async function write({
  functionName,
  args,
  value,
  onProgress,
}: WriteOptions): Promise<`0x${string}`> {
  const address = requireAddress(escrowAddress, 'VITE_ESCROW_ADDRESS');
  onProgress?.({ phase: 'validating' });

  const account = await connectWallet();
  await ensureNetwork(getProvider());

  const client = createClient({ chain, account });

  onProgress?.({ phase: 'awaiting-signature' });
  const hash = (await client.writeContract({
    address,
    functionName,
    args,
    value: value ?? 0n,
  })) as `0x${string}`;

  onProgress?.({ phase: 'submitted', hash });
  onProgress?.({ phase: 'awaiting-consensus', hash });

  await client.waitForTransactionReceipt({ hash, status: 'FINALIZED' });
  onProgress?.({ phase: 'finalized', hash });
  return hash;
}

export function createGrant(params: {
  grantee: string;
  repo: string;
  title: string;
  policyId: string;
  milestonesJson: string;
  durationDays: number;
  deposit: bigint;
  onProgress?: (progress: WriteProgress) => void;
}) {
  return write({
    functionName: 'create_grant',
    args: [
      params.grantee,
      params.repo,
      params.title,
      params.policyId,
      params.milestonesJson,
      params.durationDays,
    ],
    value: params.deposit,
    onProgress: params.onProgress,
  });
}

export function submitMilestone(params: {
  grantId: string;
  milestoneIndex: number;
  releaseTag: string;
  evidenceUrl: string;
  onProgress?: (progress: WriteProgress) => void;
}) {
  return write({
    functionName: 'submit_milestone',
    args: [params.grantId, params.milestoneIndex, params.releaseTag, params.evidenceUrl],
    onProgress: params.onProgress,
  });
}

export function reviewMilestone(params: {
  grantId: string;
  milestoneIndex: number;
  onProgress?: (progress: WriteProgress) => void;
}) {
  return write({
    functionName: 'review_milestone',
    args: [params.grantId, params.milestoneIndex],
    onProgress: params.onProgress,
  });
}

export function fileAppeal(params: {
  grantId: string;
  milestoneIndex: number;
  rebuttal: string;
  extraEvidenceUrl: string;
  bond: bigint;
  onProgress?: (progress: WriteProgress) => void;
}) {
  return write({
    functionName: 'file_appeal',
    args: [params.grantId, params.milestoneIndex, params.rebuttal, params.extraEvidenceUrl],
    value: params.bond,
    onProgress: params.onProgress,
  });
}

export function closeGrant(params: {
  grantId: string;
  onProgress?: (progress: WriteProgress) => void;
}) {
  return write({
    functionName: 'close_grant',
    args: [params.grantId],
    onProgress: params.onProgress,
  });
}

/**
 * Turn a contract error into something a human can act on.
 *
 * The contract raises `[EXPECTED] CODE` markers precisely so the UI does not
 * have to guess at intent from a stack trace.
 */
export function explainError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const marker = message.match(/\[EXPECTED\]\s+([A-Z_]+)/);
  if (marker) {
    const code = marker[1];
    return ERROR_COPY[code] ?? `The contract rejected this: ${code}.`;
  }
  if (/insufficient funds/i.test(message)) {
    return 'This account has no GEN on Studionet. Fund it from the Studio Accounts panel first.';
  }
  if (/'from'/.test(message)) {
    return 'Your wallet is on a different network. Approve the network switch and try again.';
  }
  if (/user rejected|denied/i.test(message)) return 'You cancelled the signature request.';
  return message;
}

const ERROR_COPY: Record<string, string> = {
  ALLOCATION_DEPOSIT_MISMATCH: 'Milestone allocations must add up to exactly the deposit.',
  ZERO_DEPOSIT: 'A grant needs a deposit.',
  ZERO_ALLOCATION: 'Every milestone needs a non-zero allocation.',
  SPONSOR_IS_GRANTEE: 'A sponsor cannot fund themselves.',
  DUPLICATE_CRITERION: 'Two acceptance criteria are the same. Each must be distinct.',
  INVALID_CRITERIA_COUNT: 'Each milestone needs between 2 and 12 acceptance criteria.',
  POLICY_NOT_FOUND: 'That review policy has not been published.',
  NOT_GRANTEE: 'Only the grantee named on this grant can do that.',
  NOT_SPONSOR: 'Only the sponsor who funded this grant can do that.',
  MILESTONE_NOT_SUBMITTED: 'This milestone has no evidence awaiting review.',
  MILESTONE_ALREADY_SETTLED: 'This milestone has already been settled.',
  MILESTONE_NOT_APPEALABLE: 'This milestone is not open to appeal.',
  APPEAL_ALREADY_FILED: 'An appeal has already been used on this milestone.',
  NOTHING_TO_APPEAL: 'This milestone was paid in full. There is nothing to appeal.',
  INVALID_APPEAL_BOND: 'The appeal bond must match the quoted amount exactly.',
  INVALID_REBUTTAL: 'The response needs to be at least a sentence.',
  REVIEW_LIMIT_REACHED: 'This milestone has used every review attempt its policy allows.',
  GRANT_STILL_OPEN: 'Milestones are still live and the deadline has not passed.',
  GRANT_NOT_ACTIVE: 'This grant is closed.',
  INVALID_EVIDENCE_URL: 'The evidence URL must be a public HTTPS address.',
  INVALID_RELEASE_TAG: 'That release tag contains characters this contract will not accept.',
  INVALID_REPO: 'The repository must be a plain GitHub owner/name slug.',
  INSUFFICIENT_ESCROW: 'This grant does not hold enough to cover that payout.',
};
