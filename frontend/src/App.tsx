import { useCallback, useEffect, useState } from 'react';
import { CreateGrant } from './components/CreateGrant';
import { GrantDetail } from './components/GrantDetail';
import { GrantList } from './components/GrantList';
import { Header } from './components/Header';
import { escrowAddress, policyAddress, reputationAddress } from './lib/config';
import { connectWallet, getBalance, getConnectedAccount, watchAccount } from './lib/wallet';
import { explainError } from './lib/client';

function useHashRoute(): [string, (next: string) => void] {
  const [route, setRoute] = useState(window.location.hash || '#/');
  useEffect(() => {
    const onChange = () => setRoute(window.location.hash || '#/');
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  const navigate = useCallback((next: string) => {
    window.location.hash = next;
  }, []);
  return [route, navigate];
}

function ConfigurationNotice() {
  const missing = [
    escrowAddress.status !== 'ok' && 'VITE_ESCROW_ADDRESS',
    policyAddress.status !== 'ok' && 'VITE_POLICY_ADDRESS',
    reputationAddress.status !== 'ok' && 'VITE_REPUTATION_ADDRESS',
  ].filter(Boolean);

  return (
    <div className="notice">
      <h2>Not pointed at a deployment yet</h2>
      <p>
        These environment variables are missing or malformed: <code>{missing.join(', ')}</code>
      </p>
      <p className="small muted">
        Deploy the three contracts to Studionet, then set the addresses in{' '}
        <code>frontend/.env.local</code>. The runbook is in{' '}
        <code>docs/DEPLOY-STUDIONET.md</code>. No key belongs in that file — MetaMask signs every
        write.
      </p>
    </div>
  );
}

export default function App() {
  const [route, navigate] = useHashRoute();
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [balance, setBalance] = useState<bigint | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [walletError, setWalletError] = useState<string | null>(null);

  useEffect(() => {
    void getConnectedAccount().then(setAccount).catch(() => undefined);
    return watchAccount(setAccount);
  }, []);

  useEffect(() => {
    if (!account) {
      setBalance(null);
      return;
    }
    let cancelled = false;
    getBalance(account)
      .then((value) => !cancelled && setBalance(value))
      .catch(() => !cancelled && setBalance(null));
    return () => {
      cancelled = true;
    };
  }, [account, route]);

  async function onConnect() {
    setConnecting(true);
    setWalletError(null);
    try {
      setAccount(await connectWallet());
    } catch (caught) {
      setWalletError(explainError(caught));
    } finally {
      setConnecting(false);
    }
  }

  const configured =
    escrowAddress.status === 'ok' &&
    policyAddress.status === 'ok' &&
    reputationAddress.status === 'ok';

  const grantMatch = route.match(/^#\/grant\/([0-9]+)$/);

  return (
    <div className="app">
      <Header
        account={account}
        balance={balance}
        connecting={connecting}
        onConnect={onConnect}
        onNavigate={navigate}
        route={route}
      />

      {walletError && <p className="error banner">{walletError}</p>}

      <main>
        {!configured ? (
          <ConfigurationNotice />
        ) : grantMatch ? (
          <GrantDetail grantId={grantMatch[1]} account={account} />
        ) : route.startsWith('#/new') ? (
          <CreateGrant onCreated={() => navigate('#/')} />
        ) : (
          <>
            <section className="intro">
              <h2>Grants settled by an AI jury, not a committee</h2>
              <p>
                A sponsor pins the acceptance criteria on chain and funds the escrow. A builder
                submits a release. Then every GenLayer validator independently fetches the release,
                the tag, the commit and the deliverable page, judges the criteria with its own
                model, and votes. Money moves only when they land on the same payout tier.
              </p>
              <p className="small muted">
                Browsing is read-only and needs no wallet. Connect one only to fund, submit, review
                or appeal.
              </p>
              <p className="small muted">
                To try it end-to-end: fund a grant with your own address as the builder, open the
                grant, expand a milestone, and use <em>Submit evidence</em> to hand a release tag
                to the jury.
              </p>
            </section>
            <GrantList onOpen={(grantId) => navigate(`#/grant/${grantId}`)} />
          </>
        )}
      </main>

      <footer className="footer small muted">
        <span>
          Deployed on GenLayer Studionet. Every verdict on this page was produced by validator
          consensus inside the contract — nothing here computes a result in the browser.
        </span>
      </footer>
    </div>
  );
}
