import { studionet } from 'genlayer-js/chains';

/**
 * Contract addresses come from the environment and are validated before use.
 *
 * A missing or malformed address is surfaced in the UI as a configuration
 * problem rather than being allowed to reach the SDK, where it would come back
 * as an opaque RPC error that looks like the chain is down.
 */
export type AddressState =
  | { status: 'ok'; address: `0x${string}` }
  | { status: 'missing' }
  | { status: 'invalid'; raw: string };

const ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;
const ZERO = /^0x0{40}$/i;

export function readAddress(raw: string | undefined): AddressState {
  if (raw === undefined || raw === null || raw.trim() === '') return { status: 'missing' };
  const clean = raw.trim();
  if (ZERO.test(clean)) return { status: 'invalid', raw: clean };
  if (!ADDRESS_PATTERN.test(clean)) return { status: 'invalid', raw: clean };
  return { status: 'ok', address: clean as `0x${string}` };
}

/**
 * Default contract addresses for the current Studionet deployment.
 *
 * Public addresses are not secrets, and hard-coding them as the default means a
 * new checkout builds against the right contracts even before the Vercel
 * dashboard's environment variables have been updated. A `VITE_` override still
 * wins when it is set, so a local `.env.local` or a Vercel env change points the
 * app at a different deployment without a code change.
 */
const DEFAULT_ESCROW = '0x57c7fA920F4407d084E47ED5E05fCfc7d56D9e00';
const DEFAULT_POLICY = '0xb757eC8a9824Eb956072d7E6Bc5D5bC4ad597CAb';
const DEFAULT_REPUTATION = '0xea3DDF603bBDFDcdEA1a9F92FCeE95c42C3daC26';

function firstNonEmpty(...values: (string | undefined)[]): string | undefined {
  for (const value of values) {
    if (typeof value === 'string' && value.trim() !== '') return value;
  }
  return undefined;
}

export const escrowAddress = readAddress(
  firstNonEmpty(import.meta.env.VITE_ESCROW_ADDRESS, DEFAULT_ESCROW),
);
export const policyAddress = readAddress(
  firstNonEmpty(import.meta.env.VITE_POLICY_ADDRESS, DEFAULT_POLICY),
);
export const reputationAddress = readAddress(
  firstNonEmpty(import.meta.env.VITE_REPUTATION_ADDRESS, DEFAULT_REPUTATION),
);

export const configured = escrowAddress.status === 'ok';

/**
 * Chain metadata is read from the SDK rather than hardcoded, so a change on
 * GenLayer's side is picked up by rebuilding instead of by editing constants.
 */
export const chain = studionet;
export const chainIdHex = `0x${studionet.id.toString(16)}` as const;

/**
 * Explorer base URL.
 *
 * Everything else about the chain is read from the SDK, but
 * `studionet.blockExplorers` currently points at a host that answers 503. That
 * would leave every "view on the explorer" link dead — the one place a
 * sceptical reader goes to confirm any of this is real — so the working
 * Studionet explorer is pinned here instead.
 *
 * Revert this to `studionet.blockExplorers.default.url` once that host is back.
 */
const EXPLORER_BASE = 'https://explorer-studio.genlayer.com';

function explorerLink(kind: 'tx' | 'address', value?: string): string | null {
  if (!EXPLORER_BASE || !value) return null;
  return `${EXPLORER_BASE.replace(/\/$/, '')}/${kind}/${value}`;
}

export function explorerTx(hash?: string): string | null {
  return explorerLink('tx', hash);
}

export function explorerAddress(address?: string): string | null {
  return explorerLink('address', address);
}
