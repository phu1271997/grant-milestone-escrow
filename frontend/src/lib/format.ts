import type { Tier } from './types';

const DECIMALS = 18n;
const ONE = 10n ** DECIMALS;

/**
 * Parse a human GEN amount into wei without ever touching a float.
 *
 * `parseFloat('0.1') * 1e18` is off by hundreds of wei, which is invisible in a
 * demo and wrong in an escrow. Everything here is string and bigint.
 */
export function parseGen(input: string): bigint {
  const clean = input.trim();
  if (!/^\d+(\.\d+)?$/.test(clean)) {
    throw new Error(`"${input}" is not a valid GEN amount.`);
  }
  const [whole, fraction = ''] = clean.split('.');
  if (fraction.length > Number(DECIMALS)) {
    throw new Error(`GEN amounts support at most ${DECIMALS} decimal places.`);
  }
  const padded = fraction.padEnd(Number(DECIMALS), '0');
  return BigInt(whole) * ONE + BigInt(padded || '0');
}

/** Format wei as GEN, trimming trailing zeros but never rounding. */
export function formatGen(wei: bigint | string, maxFractionDigits = 4): string {
  const value = typeof wei === 'string' ? BigInt(wei) : wei;
  const negative = value < 0n;
  const abs = negative ? -value : value;

  const whole = abs / ONE;
  const fraction = (abs % ONE).toString().padStart(Number(DECIMALS), '0');
  let shown = fraction.slice(0, maxFractionDigits).replace(/0+$/, '');
  if (shown === '') shown = '';

  const grouped = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${negative ? '-' : ''}${grouped}${shown ? `.${shown}` : ''}`;
}

export function shortAddress(address: string): string {
  if (!address || address.length < 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function shortSha(sha: string): string {
  return sha ? sha.slice(0, 10) : '';
}

export function formatDate(iso: string): string {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function percentFromBps(bps: string): string {
  return `${(Number(bps) / 100).toFixed(0)}%`;
}

export const TIER_COPY: Record<Tier, { label: string; blurb: string; tone: string }> = {
  COMPLETE: {
    label: 'Complete',
    blurb: 'Every acceptance criterion was met. The full allocation was released.',
    tone: 'tone-complete',
  },
  SUBSTANTIAL: {
    label: 'Substantial',
    blurb: 'Most criteria were met. A reduced share of the allocation was released.',
    tone: 'tone-substantial',
  },
  PARTIAL: {
    label: 'Partial',
    blurb: 'About half the criteria were met. A partial share was released.',
    tone: 'tone-partial',
  },
  INSUFFICIENT: {
    label: 'Insufficient',
    blurb: 'Too few criteria were met for any release.',
    tone: 'tone-insufficient',
  },
  REJECTED: {
    label: 'Rejected',
    blurb: 'The evidence was disqualifying rather than merely thin. Nothing was released.',
    tone: 'tone-rejected',
  },
  NEEDS_CLARIFICATION: {
    label: 'Needs clarification',
    blurb:
      'The jury could not reach a reading it trusted. Nothing was released and nothing counts against the builder — resubmit and try again.',
    tone: 'tone-clarify',
  },
};
