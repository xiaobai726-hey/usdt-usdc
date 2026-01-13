#!/usr/bin/env python3
"""
USDT/USDC monitor (Curve 3pool + multi-chain providers).

Step 1 (done): Connect Ethereum mainnet + Base, read Curve 3pool USDT/USDC balances and ratio.
Step 2/3 (WIP): CEX depth integration + prediction/alerting.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from web3 import Web3


# Curve 3pool (Ethereum mainnet)
# Swap contract (not LP token).
CURVE_3POOL_SWAP = Web3.to_checksum_address("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")

# 3pool coins indices: 0=DAI, 1=USDC, 2=USDT
USDC_INDEX = 1
USDT_INDEX = 2

USDC_DECIMALS = 6
USDT_DECIMALS = 6

CURVE_SWAP_ABI: list[dict[str, Any]] = [
    {
        "name": "balances",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [{"type": "uint256", "name": "i"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "coins",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [{"type": "uint256", "name": "i"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass(frozen=True)
class ChainConfig:
    name: str
    rpc_env: str


CHAINS: list[ChainConfig] = [
    ChainConfig(name="ethereum", rpc_env="ETH_RPC_URL"),
    ChainConfig(name="base", rpc_env="BASE_RPC_URL"),
]


def _require_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def connect_providers() -> dict[str, Web3]:
    """Create Web3 providers for configured chains."""
    w3s: dict[str, Web3] = {}
    for c in CHAINS:
        rpc_url = _require_env(c.rpc_env)
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        if not w3.is_connected():
            raise SystemExit(f"Failed to connect: {c.name} ({c.rpc_env})")
        w3s[c.name] = w3
    return w3s


def _from_units(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** Decimal(decimals))


def read_curve_3pool_usdt_usdc(w3_eth: Web3) -> dict[str, Any]:
    """Read 3pool USDT/USDC balances (swap contract 'balances')."""
    swap = w3_eth.eth.contract(address=CURVE_3POOL_SWAP, abi=CURVE_SWAP_ABI)

    usdc_raw: int = swap.functions.balances(USDC_INDEX).call()
    usdt_raw: int = swap.functions.balances(USDT_INDEX).call()

    usdc = _from_units(usdc_raw, USDC_DECIMALS)
    usdt = _from_units(usdt_raw, USDT_DECIMALS)

    total = usdc + usdt
    if total == 0:
        usdt_share = Decimal("0")
        usdc_share = Decimal("0")
        usdt_over_usdc = None
    else:
        usdt_share = usdt / total  # 0..1
        usdc_share = usdc / total
        usdt_over_usdc = (usdt / usdc) if usdc != 0 else None

    return {
        "pool": "curve-3pool",
        "chain": "ethereum",
        "usdc": usdc,
        "usdt": usdt,
        "usdt_share": usdt_share,  # 0..1
        "usdc_share": usdc_share,  # 0..1
        "usdt_over_usdc": usdt_over_usdc,  # None if divisor 0
    }


def main() -> int:
    w3s = connect_providers()
    # Base is connected for multi-chain readiness; 3pool exists on Ethereum mainnet only.
    snapshot = read_curve_3pool_usdt_usdc(w3s["ethereum"])

    usdt_pct = (snapshot["usdt_share"] * Decimal(100)).quantize(Decimal("0.01"))
    usdc_pct = (snapshot["usdc_share"] * Decimal(100)).quantize(Decimal("0.01"))
    ratio = snapshot["usdt_over_usdc"]
    ratio_str = "N/A" if ratio is None else str(ratio.quantize(Decimal("0.00000001")))

    print("Curve 3pool (Ethereum) balances:")
    print(f"  USDC: {snapshot['usdc']}")
    print(f"  USDT: {snapshot['usdt']}")
    print(f"  Share: USDT {usdt_pct}% | USDC {usdc_pct}%")
    print(f"  USDT/USDC ratio: {ratio_str}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
