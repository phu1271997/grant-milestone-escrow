#!/usr/bin/env node
/**
 * Seed a demonstration grant on Studionet.
 *
 * Judges opening an empty registry cannot tell a working system from a static
 * page, so it is worth having one real grant in there with a real review
 * attached. This script does that end to end without any clicking.
 *
 * ## Keys
 *
 * Private keys are read from the environment and are never written to disk,
 * never logged, and never committed. Export them in your own shell:
 *
 *   export SPONSOR_PRIVATE_KEY=0x...
 *   export BUILDER_PRIVATE_KEY=0x...
 *
 * Both accounts need a GEN balance on Studionet, and they must be different
 * accounts — the contract rejects a sponsor funding themselves, and a demo
 * where one party approves its own work is the exact thing this project argues
 * against.
 *
 * A key that has ever been pasted into a chat window, a ticket, or a shared
 * document should be treated as public. Use throwaway accounts here and do not
 * reuse them for anything that later matters.
 *
 * ## Order
 *
 *   node scripts/seed-demo-grant.mjs fund
 *   # ...now publish the GitHub release. It MUST be published after funding:
 *   # the contract blocks any release that predates its grant.
 *   node scripts/seed-demo-grant.mjs submit <grantId> <tag>
 *   node scripts/seed-demo-grant.mjs review <grantId>
 *
 * `status <grantId>` prints the current state at any point.
 */

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
let createAccount;
let createClient;
let studionet;
let TransactionStatus;
try {
  ({ createAccount, createClient } = await import(
    pathToFileURL(require.resolve('genlayer-js')).href
  ));
  ({ studionet } = await import(pathToFileURL(require.resolve('genlayer-js/chains')).href));
  ({ TransactionStatus } = await import(
    pathToFileURL(require.resolve('genlayer-js/types')).href
  ));
} catch (error) {
  console.error('Could not load genlayer-js. Run `npm ci` in frontend/ first.');
  console.error(error?.message ?? error);
  process.exit(4);
}

const GEN = 10n ** 18n;

const GRANT = {
  repo: 'phu1271997/grant-milestone-escrow',
  title: 'GrantMilestoneEscrow reference build',
  policyId: 'standard-v1',
  durationDays: 180,
  deliverableUrl: 'https://grant-milestone-escrow.vercel.app',
  milestones: [
    {
      title: 'Ship the escrow, the app, and the test suite',
      allocation: (GEN * 3n) / 100n,
      criteria: [
        'The escrow, policy and reputation contracts are deployed to GenLayer Studionet and their addresses are published.',
        'A public web app is deployed that reads grant state directly from the deployed contract.',
        'The repository contains an automated test suite covering the validator agreement rules.',
      ],
    },
    {
      title: 'Record a walkthrough and publish the runbook',
      allocation: (GEN * 2n) / 100n,
      criteria: [
        'A recorded demo walkthrough of the full grant lifecycle is published and linked.',
        'A step-by-step Studionet deployment runbook is published in the repository.',
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function escrowAddress() {
  const fromArgv = process.env.ESCROW_ADDRESS;
  if (fromArgv) return fromArgv;
  try {
    const text = readFileSync(new URL('../frontend/.env.local', import.meta.url), 'utf8');
    const match = text.match(/^\s*VITE_ESCROW_ADDRESS\s*=\s*(0x[0-9a-fA-F]{40})\s*$/m);
    if (match) return match[1];
  } catch {
    /* fall through */
  }
  fail('No escrow address. Set ESCROW_ADDRESS or fill in frontend/.env.local.');
}

function accountFrom(varName) {
  const raw = process.env[varName];
  if (!raw) {
    fail(
      `${varName} is not set.\n` +
        `Export it in your shell first — it is never read from a file and never written to one:\n` +
        `  export ${varName}=0x...`,
    );
  }
  const key = raw.trim().startsWith('0x') ? raw.trim() : `0x${raw.trim()}`;
  if (!/^0x[0-9a-fA-F]{64}$/.test(key)) fail(`${varName} is not a 32-byte hex private key.`);
  return createAccount(key);
}

function fail(message) {
  console.error(`\n${message}\n`);
  process.exit(2);
}

const reader = createClient({ chain: studionet });

async function readJson(address, functionName, args = []) {
  const raw = await reader.readContract({ address, functionName, args });
  return typeof raw === 'string' ? JSON.parse(raw) : raw;
}

async function send(account, functionName, args, value = 0n) {
  const client = createClient({ chain: studionet, account });
  const address = escrowAddress();

  process.stdout.write(`  → ${functionName} … `);
  const hash = await client.writeContract({ address, functionName, args, value });
  process.stdout.write(`${hash}\n    waiting for consensus … `);

  const receipt = await client.waitForTransactionReceipt({
    hash,
    status: TransactionStatus.FINALIZED,
  });

  const execution = receipt?.txExecutionResultName;
  if (execution === 'FINISHED_WITH_ERROR') {
    console.log('reverted');
    const leader = receipt?.consensus_data?.leader_receipt?.[0];
    console.error('\nThe transaction finalized but reverted inside the contract.');
    if (leader?.error) console.error(String(leader.error));
    process.exit(1);
  }
  console.log('ok');
  return receipt;
}

async function requireBalance(account, label) {
  const balance = await reader.getBalance({ address: account.address });
  console.log(`  ${label.padEnd(8)} ${account.address}  ${formatGen(balance)} GEN`);
  if (balance === 0n) {
    fail(
      `${label} has no GEN on Studionet. Fund it from the Studio Accounts panel ` +
        `before running this — the hosted RPC will not fund an address for you.`,
    );
  }
}

function formatGen(wei) {
  const whole = wei / GEN;
  const fraction = (wei % GEN).toString().padStart(18, '0').slice(0, 4).replace(/0+$/, '');
  return fraction ? `${whole}.${fraction}` : `${whole}`;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function fund() {
  const sponsor = accountFrom('SPONSOR_PRIVATE_KEY');
  const builder = accountFrom('BUILDER_PRIVATE_KEY');

  if (sponsor.address.toLowerCase() === builder.address.toLowerCase()) {
    fail('Sponsor and builder must be different accounts. The contract rejects the alternative.');
  }

  console.log('\nAccounts');
  await requireBalance(sponsor, 'sponsor');
  await requireBalance(builder, 'builder');

  const deposit = GRANT.milestones.reduce((total, m) => total + m.allocation, 0n);
  const payload = GRANT.milestones.map((m) => ({
    title: m.title,
    allocation: m.allocation.toString(),
    criteria: m.criteria,
  }));

  console.log(`\nFunding ${formatGen(deposit)} GEN across ${payload.length} milestones`);
  await send(
    sponsor,
    'create_grant',
    [
      builder.address,
      GRANT.repo,
      GRANT.title,
      GRANT.policyId,
      JSON.stringify(payload),
      GRANT.durationDays,
    ],
    deposit,
  );

  const grants = await readJson(escrowAddress(), 'get_grants', [0, 50]);
  const grant = grants.items[grants.items.length - 1];
  console.log(`\nGrant #${grant.grant_id} funded, created at ${grant.created_at}`);
  console.log(
    `\nNext: publish the GitHub release NOW — after this timestamp, not before.\n` +
      `The contract blocks any release published earlier than its grant.\n\n` +
      `  node scripts/seed-demo-grant.mjs submit ${grant.grant_id} v1.0.0\n`,
  );
}

async function submit(grantId, tag) {
  if (!grantId || !tag) fail('Usage: seed-demo-grant.mjs submit <grantId> <tag>');
  const builder = accountFrom('BUILDER_PRIVATE_KEY');

  console.log(`\nSubmitting ${tag} as evidence for grant #${grantId}, milestone 1`);
  await send(builder, 'submit_milestone', [grantId, 0, tag, GRANT.deliverableUrl]);
  console.log(`\nNext:\n\n  node scripts/seed-demo-grant.mjs review ${grantId}\n`);
}

async function review(grantId) {
  if (!grantId) fail('Usage: seed-demo-grant.mjs review <grantId>');
  const caller = accountFrom('BUILDER_PRIVATE_KEY');

  console.log(`\nConvening the jury on grant #${grantId}, milestone 1.`);
  console.log('Every validator now fetches the release, the tag, the commit and the');
  console.log('deliverable page, then judges the criteria with its own model. This is');
  console.log('slower than an ordinary transaction, and that is the product working.\n');

  await send(caller, 'review_milestone', [grantId, 0]);
  await status(grantId);
}

async function status(grantId) {
  if (!grantId) fail('Usage: seed-demo-grant.mjs status <grantId>');
  const { grant, milestones } = await readJson(escrowAddress(), 'get_grant', [grantId]);

  console.log(`\nGrant #${grant.grant_id} — ${grant.title}`);
  console.log(`  repo       ${grant.repo}`);
  console.log(`  escrowed   ${formatGen(BigInt(grant.escrowed))} GEN`);
  console.log(`  released   ${formatGen(BigInt(grant.released))} GEN`);

  const STATES = ['open', 'submitted', 'settled', 'final'];
  for (const milestone of milestones) {
    const tier = milestone.settled_tier || STATES[Number(milestone.state)];
    console.log(
      `\n  M${Number(milestone.index) + 1}  ${milestone.title}\n` +
        `      ${formatGen(BigInt(milestone.allocation))} GEN · ${tier} · ` +
        `paid ${formatGen(BigInt(milestone.paid_amount))} GEN`,
    );
    if (milestone.latest_review_id) {
      const r = await readJson(escrowAddress(), 'get_review', [milestone.latest_review_id]);
      console.log(
        `      review #${r.review_id}: ${r.met_count}/${r.total_count} met, ` +
          `confidence ${r.confidence}%, commit ${r.commit_sha.slice(0, 10) || '—'}`,
      );
      for (const key of [...r.blockers, ...r.gaps]) console.log(`        · ${key}`);
    }
  }
  console.log('');
}

const [command, ...rest] = process.argv.slice(2);
const commands = { fund, submit, review, status };

if (!commands[command]) {
  console.error(
    '\nUsage:\n' +
      '  node scripts/seed-demo-grant.mjs fund\n' +
      '  node scripts/seed-demo-grant.mjs submit <grantId> <tag>\n' +
      '  node scripts/seed-demo-grant.mjs review <grantId>\n' +
      '  node scripts/seed-demo-grant.mjs status <grantId>\n\n' +
      'Requires SPONSOR_PRIVATE_KEY and BUILDER_PRIVATE_KEY in the environment.\n',
  );
  process.exit(2);
}

commands[command](...rest).catch((error) => {
  console.error(`\n${error?.message ?? error}\n`);
  process.exit(1);
});
