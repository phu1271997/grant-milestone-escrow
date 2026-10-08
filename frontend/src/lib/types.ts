/**
 * Shapes returned by the contract views.
 *
 * Every numeric field arrives as a decimal string. That is deliberate on the
 * contract side — `JSON.parse` would silently round an 18-decimal allocation —
 * so nothing here converts to `number`. Amounts stay `bigint` end to end and
 * are only formatted at the point of display.
 */

export type Tier =
  | 'COMPLETE'
  | 'SUBSTANTIAL'
  | 'PARTIAL'
  | 'INSUFFICIENT'
  | 'REJECTED'
  | 'NEEDS_CLARIFICATION';

export const MilestoneState = {
  Open: '0',
  Submitted: '1',
  Settled: '2',
  Final: '3',
} as const;

export interface Grant {
  grant_id: string;
  sponsor: string;
  grantee: string;
  repo: string;
  title: string;
  policy_id: string;
  deposit: string;
  escrowed: string;
  released: string;
  milestone_count: string;
  settled_count: string;
  status: string;
  created_at: string;
  deadline_at: string;
}

export interface Milestone {
  grant_id: string;
  index: string;
  title: string;
  criteria: string[];
  requirement_ids: string[];
  requirement_count: string;
  allocation: string;
  state: string;
  release_tag: string;
  evidence_url: string;
  submitted_at: string;
  review_count: string;
  latest_review_id: string;
  settled_tier: Tier | '';
  settled_payout_bps: string;
  paid_amount: string;
  appeal_filed: boolean;
  appeal_bond: string;
  appeal_deadline_at: string;
}

export interface Review {
  review_id: string;
  grant_id: string;
  milestone_index: string;
  reviewer: string;
  kind: string;
  release_tag: string;
  commit_sha: string;
  evidence_url: string;
  evidence_fingerprint: string;
  met_count: string;
  total_count: string;
  blocker_mask: string;
  gap_mask: string;
  blockers: string[];
  gaps: string[];
  confidence: string;
  tier: Tier;
  payout_bps: string;
  paid_amount: string;
  created_at: string;
}

export interface Reputation {
  builder: string;
  settlements: string;
  complete: string;
  substantial: string;
  partial: string;
  insufficient: string;
  rejected: string;
  clarifications: string;
  appeals_filed: string;
  appeals_upheld: string;
  total_paid: string;
  first_seen_at: string;
  last_seen_at: string;
  known: boolean;
}

export interface Policy {
  policy_id: string;
  label: string;
  substantial_permille: string;
  partial_permille: string;
  substantial_payout_bps: string;
  partial_payout_bps: string;
  confidence_threshold: string;
  appeal_bond_bps: string;
  min_appeal_bond: string;
  max_reviews_per_milestone: string;
  publisher: string;
  created_at: string;
}

export interface AppealQuote {
  required_bond: string;
  appealable: boolean;
  current_tier: Tier | '';
  current_payout_bps: string;
  appeal_deadline_at: string;
}

export interface Page<T> {
  cursor: string;
  items: T[];
  next_cursor: string | null;
  total: string;
}

export interface MilestoneDraft {
  title: string;
  allocationGen: string;
  criteria: string[];
}

/** Human-readable copy for every taxonomy key the contract can record. */
export const OBSERVATION_LABELS: Record<string, string> = {
  release_predates_grant: 'The release was published before this grant existed',
  source_commit_conflict: 'GitHub views of this tag disagree about the commit',
  commit_not_in_repository: 'The tag points at a commit outside this repository',
  unrelated_repository: 'The evidence describes a different project',
  criteria_not_addressed: 'The submission does not engage the acceptance criteria',
  fabricated_evidence: 'The deliverable page contradicts the release',
  artifact_absent_from_release: 'A named artefact is missing from the release',
  release_source_unreachable: 'A GitHub endpoint did not answer',
  evidence_page_unreachable: 'The deliverable page did not load',
  llm_output_unusable: 'The jury returned an unusable answer',
  requirement_coverage_incomplete: 'The jury did not classify every requirement',
  requirement_id_unknown: 'The jury referred to a requirement that does not exist',
  confidence_below_policy_floor: 'The jury was less certain than this policy allows',
  deliverable_unverifiable: 'The evidence cannot be checked either way',
  criteria_ambiguous: 'A criterion admits more than one reading',
};
