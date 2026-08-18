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

export const escrowAddress = readAddress(import.meta.env.VITE_ESCROW_ADDRESS);
export const policyAddress = readAddress(import.meta.env.VITE_POLICY_ADDRESS);
export const reputationAddress = readAddress(import.meta.env.VITE_REPUTATION_ADDRESS);

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
