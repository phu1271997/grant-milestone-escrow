import { chain, escrowAddress, explorerAddress } from '../lib/config';
import { formatGen, shortAddress } from '../lib/format';

interface HeaderProps {
  account: `0x${string}` | null;
  balance: bigint | null;
  connecting: boolean;
  onConnect: () => void;
  onNavigate: (route: string) => void;
  route: string;
}

export function Header({
  account,
  balance,
  connecting,
  onConnect,
  onNavigate,
  route,
}: HeaderProps) {
  const contractLink =
    escrowAddress.status === 'ok' ? explorerAddress(escrowAddress.address) : null;

  return (
    <header className="header">
      <div className="header-brand">
        <button className="brand" onClick={() => onNavigate('#/')}>
          <span className="brand-mark" aria-hidden="true" />
          GrantMilestoneEscrow
        </button>
        <p className="brand-tagline">
          Milestones settle when independent AI validators agree how complete the work is.
        </p>
      </div>

      <nav className="header-nav">
        <button
          className={route.startsWith('#/new') ? 'nav-link active' : 'nav-link'}
          onClick={() => onNavigate('#/new')}
        >
          Fund a grant
        </button>
        <button
          className={route === '#/' || route === '' ? 'nav-link active' : 'nav-link'}
          onClick={() => onNavigate('#/')}
        >
          Registry
        </button>
      </nav>

      <div className="header-wallet">
        {account ? (
          <div className="wallet-chip" title={account}>
            <span className="mono">{shortAddress(account)}</span>
            <span className="wallet-balance">
              {balance === null ? '…' : `${formatGen(balance, 3)} ${chain.nativeCurrency.symbol}`}
            </span>
          </div>
        ) : (
          <button className="primary" onClick={onConnect} disabled={connecting}>
            {connecting ? 'Connecting…' : 'Connect wallet'}
          </button>
        )}
        <div className="chain-note small">
          {chain.name}
          {contractLink && (
            <>
              {' · '}
              <a href={contractLink} target="_blank" rel="noreferrer noopener">
                contract ↗
              </a>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
