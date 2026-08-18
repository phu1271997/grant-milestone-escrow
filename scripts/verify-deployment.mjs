#!/usr/bin/env node
/**
 * Verify a Studionet deployment before trusting it.
 *
 * Deploying three contracts that have to know about each other has exactly one
 * interesting failure mode: they deploy fine and are wired to the wrong
 * addresses. Nothing errors — the escrow just writes reputation records into
 * the void, and you find out during the demo.
 *
 * This reads all three contracts and checks the wiring is mutually consistent,
 * which is the thing a green deploy log does not tell you.
 *
 * Usage, from anywhere in the repository:
 *
 *   node scripts/verify-deployment.mjs <escrow> <policy> <reputation>
 *
 * Or with no arguments, reading frontend/.env.local.
 */

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

/**
 * Node resolves bare imports relative to *this file*, not the working
 * directory, so `genlayer-js` is invisible from scripts/ even when the frontend
 * has it installed. Resolving through frontend/package.json borrows the SDK
 * that the app itself is built against — which is also the version you want to
 * be verifying with.
 */
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
let createClient;
let studionet;
try {
  ({ createClient } = await import(pathToFileURL(require.resolve('genlayer-js')).href));
  ({ studionet } = await import(pathToFileURL(require.resolve('genlayer-js/chains')).href));
} catch (error) {
  console.error('Could not load genlayer-js. Run `npm ci` in frontend/ first.');
  console.error(error?.message ?? error);
  process.exit(4);
}

const PASS = '  ok   ';
const FAIL = ' FAIL  ';

function readEnvLocal() {
  try {
    const text = readFileSync(new URL('../frontend/.env.local', import.meta.url), 'utf8');
    const found = {};
    for (const line of text.split('\n')) {
      const match = line.match(/^\s*(VITE_[A-Z_]+)\s*=\s*(.*?)\s*$/);
      if (match) found[match[1]] = match[2];
    }
    return found;
  } catch {
    return {};
  }
}

function resolveAddresses() {
  const [escrow, policy, reputation] = process.argv.slice(2);
  if (escrow && policy && reputation) return { escrow, policy, reputation };

  const env = readEnvLocal();
  return {
    escrow: env.VITE_ESCROW_ADDRESS,
    policy: env.VITE_POLICY_ADDRESS,
    reputation: env.VITE_REPUTATION_ADDRESS,
  };
}

const results = [];
function check(label, condition, detail = '') {
  results.push({ label, ok: Boolean(condition), detail });
  console.log(`${condition ? PASS : FAIL} ${label}${detail ? ` — ${detail}` : ''}`);
}

async function main() {
  const addresses = resolveAddresses();
  for (const [name, value] of Object.entries(addresses)) {
    if (!/^0x[0-9a-fA-F]{40}$/.test(value ?? '')) {
      console.error(`Missing or malformed ${name} address: ${value ?? '(unset)'}`);
      console.error('Pass all three on the command line, or fill in frontend/.env.local.');
      process.exit(2);
    }
  }

  const client = createClient({ chain: studionet });
  const read = async (address, functionName, args = []) => {
    const raw = await client.readContract({ address, functionName, args });
    return typeof raw === 'string' ? JSON.parse(raw) : raw;
  };

  console.log(`\nStudionet · chain id ${studionet.id}\n`);

  const bindings = await read(addresses.escrow, 'get_bindings');
  console.log(`escrow      ${addresses.escrow}`);
  console.log(`policy      ${addresses.policy}`);
  console.log(`reputation  ${addresses.reputation}\n`);

  check(
    'escrow points at the policy contract you deployed',
    bindings.policy_contract?.toLowerCase() === addresses.policy.toLowerCase(),
    bindings.policy_contract,
  );
  check(
    'escrow points at the reputation contract you deployed',
    bindings.reputation_contract?.toLowerCase() === addresses.reputation.toLowerCase(),
    bindings.reputation_contract,
  );

  const binding = await read(addresses.reputation, 'get_binding');
  check('reputation ledger has been bound', binding.bound === true);
  check(
    'reputation ledger is bound to this escrow',
    binding.escrow?.toLowerCase() === addresses.escrow.toLowerCase(),
    binding.escrow,
  );

  const policies = await read(addresses.policy, 'get_policies');
  check(
    'at least one review policy is published',
    Number(policies.total) > 0,
    `${policies.total} published: ${policies.items.map((p) => p.policy_id).join(', ') || 'none'}`,
  );

  const taxonomy = await read(addresses.escrow, 'get_taxonomy');
  check(
    'escrow publishes its observation taxonomy',
    Array.isArray(taxonomy.blockers) && taxonomy.blockers.length > 0,
    `${taxonomy.blockers?.length} blockers, ${taxonomy.gaps?.length} gaps`,
  );

  const failed = results.filter((entry) => !entry.ok);
  if (failed.length) {
    console.log(`\n${failed.length} check(s) failed. Do not demo this deployment.\n`);
    process.exit(1);
  }
  console.log('\nAll checks passed. The three contracts are mutually wired.\n');
}

main().catch((error) => {
  console.error('\nVerification could not complete:', error?.message ?? error);
  console.error('If this is a connection error, confirm Studionet is reachable.\n');
  process.exit(3);
});
