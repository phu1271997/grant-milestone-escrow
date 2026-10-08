#!/usr/bin/env python3
"""Deploy the three GrantMilestoneEscrow contracts to Studionet.

Reads the deployer key from GENLAYER_PRIVATE_KEY (see ~/.genlayer/env.sh), then:

  1. pre-flights every contract's storage schema,
  2. deploys MilestonePolicy and publishes the `standard-v1` policy,
  3. deploys BuilderReputation,
  4. deploys GrantEscrow pointed at the two above,
  5. binds the reputation ledger to the escrow,
  6. verifies the wiring through the on-chain views.

Writes wait for ACCEPTED, not FINALIZED: Studionet finalisation takes minutes and
ACCEPTED already carries committed state and the leader result.
"""

import json
import os
import sys
import time
from pathlib import Path

from genlayer_py import create_account, create_client, studionet
from genlayer_py.types import TransactionStatus

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
POLICY_SPEC = json.loads((ROOT / "scripts" / "bootstrap-policy.json").read_text())["standard-v1"]

WAIT = dict(status=TransactionStatus.ACCEPTED, interval=4000, retries=150)


def _addr_from_receipt(receipt: dict) -> str:
    """Pull the new contract address off a deploy receipt (a dict)."""
    data = receipt.get("data")
    if isinstance(data, dict):
        value = data.get("contract_address")
        if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
            return value
    for key in ("to_address", "recipient"):
        value = receipt.get(key)
        if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
            return value
    raise RuntimeError("could not find deployed contract address in receipt")


def _assert_ok(receipt: dict, what: str) -> None:
    """A FINALIZED/ACCEPTED tx can still have reverted — check the leader result."""
    cd = receipt.get("consensus_data") if isinstance(receipt, dict) else None
    try:
        exec_result = cd["leader_receipt"][0]["execution_result"]
    except Exception:
        exec_result = None
    if exec_result == "ERROR":
        stderr = ""
        try:
            stderr = cd["leader_receipt"][0]["genvm_result"]["stderr"]
        except Exception:
            pass
        raise RuntimeError(f"{what} reverted on-chain:\n{stderr}")


def main() -> None:
    pk = os.environ.get("GENLAYER_PRIVATE_KEY")
    if not pk or pk.startswith("0xREPLACE"):
        sys.exit("GENLAYER_PRIVATE_KEY not set. Run: source ~/.genlayer/env.sh")

    account = create_account(pk)
    client = create_client(chain=studionet, account=account)
    print(f"Deployer: {account.address}")

    policy_code = (CONTRACTS / "milestone_policy.py").read_text()
    reputation_code = (CONTRACTS / "builder_reputation.py").read_text()
    escrow_code = (CONTRACTS / "grant_escrow.py").read_text()

    print("Pre-flighting contract schemas...")
    for name, code in (("policy", policy_code), ("reputation", reputation_code), ("escrow", escrow_code)):
        client.get_contract_schema_for_code(code.encode())
        print(f"  {name}: schema OK")

    # 1. MilestonePolicy -----------------------------------------------------
    print("Deploying MilestonePolicy...")
    tx = client.deploy_contract(code=policy_code, account=account)
    r = client.wait_for_transaction_receipt(transaction_hash=tx, **WAIT)
    _assert_ok(r, "policy deploy")
    policy_addr = _addr_from_receipt(r)
    print(f"  POLICY_ADDRESS = {policy_addr}")

    # 2. publish standard-v1 -------------------------------------------------
    print("Publishing policy standard-v1...")
    tx = client.write_contract(
        address=policy_addr,
        function_name="publish_policy",
        account=account,
        args=[
            POLICY_SPEC["policy_id"],
            POLICY_SPEC["label"],
            int(POLICY_SPEC["substantial_permille"]),
            int(POLICY_SPEC["partial_permille"]),
            int(POLICY_SPEC["substantial_payout_bps"]),
            int(POLICY_SPEC["partial_payout_bps"]),
            int(POLICY_SPEC["confidence_threshold"]),
            int(POLICY_SPEC["appeal_bond_bps"]),
            int(POLICY_SPEC["min_appeal_bond"]),
            int(POLICY_SPEC["max_reviews_per_milestone"]),
        ],
    )
    r = client.wait_for_transaction_receipt(transaction_hash=tx, **WAIT)
    _assert_ok(r, "publish_policy")

    # 3. BuilderReputation ---------------------------------------------------
    print("Deploying BuilderReputation...")
    tx = client.deploy_contract(code=reputation_code, account=account)
    r = client.wait_for_transaction_receipt(transaction_hash=tx, **WAIT)
    _assert_ok(r, "reputation deploy")
    reputation_addr = _addr_from_receipt(r)
    print(f"  REPUTATION_ADDRESS = {reputation_addr}")

    # 4. GrantEscrow ---------------------------------------------------------
    print("Deploying GrantEscrow...")
    tx = client.deploy_contract(code=escrow_code, account=account, args=[policy_addr, reputation_addr])
    r = client.wait_for_transaction_receipt(transaction_hash=tx, **WAIT)
    _assert_ok(r, "escrow deploy")
    escrow_addr = _addr_from_receipt(r)
    print(f"  ESCROW_ADDRESS = {escrow_addr}")

    # 5. bind reputation -> escrow ------------------------------------------
    print("Binding BuilderReputation -> GrantEscrow...")
    tx = client.write_contract(
        address=reputation_addr, function_name="bind_escrow", account=account, args=[escrow_addr]
    )
    r = client.wait_for_transaction_receipt(transaction_hash=tx, **WAIT)
    _assert_ok(r, "bind_escrow")

    # 6. verify wiring -------------------------------------------------------
    print("Verifying wiring...")
    bindings = json.loads(client.read_contract(address=escrow_addr, function_name="get_bindings"))
    assert bindings["policy_contract"].lower() == policy_addr.lower(), bindings
    assert bindings["reputation_contract"].lower() == reputation_addr.lower(), bindings
    assert client.read_contract(address=policy_addr, function_name="policy_exists", args=["standard-v1"]) is True
    print("  wiring OK")

    print("\n=== Deployment complete ===")
    print(f"VITE_POLICY_ADDRESS={policy_addr}")
    print(f"VITE_REPUTATION_ADDRESS={reputation_addr}")
    print(f"VITE_ESCROW_ADDRESS={escrow_addr}")
    (ROOT / "scripts" / "last-deploy.json").write_text(
        json.dumps(
            {"policy": policy_addr, "reputation": reputation_addr, "escrow": escrow_addr},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
