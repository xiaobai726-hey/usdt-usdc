#!/usr/bin/env python3
"""
USDT/USDC monitor (Curve 3pool + multi-chain providers).

Step 1 (done): Connect Ethereum mainnet + Base, read Curve 3pool USDT/USDC balances and ratio.
Step 2 (done): CEX top-of-book + Curve simulated 1M swap and basis.
Step 3 (WIP): Prediction/alerting.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import ccxt
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
        "name": "get_dy",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [
            {"type": "int128", "name": "i"},
            {"type": "int128", "name": "j"},
            {"type": "uint256", "name": "dx"},
        ],
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


def _safe_decimal(x: Any) -> Decimal:
    # ccxt can return floats; normalize to Decimal through str.
    return Decimal(str(x))


def fetch_cex_top_of_book() -> dict[str, dict[str, Decimal | None]]:
    """
    Fetch top-of-book for USDT/USDC on Binance + Coinbase.

    Returns:
      {exchange: {bid, ask, mid}} in "USDC per 1 USDT".
    """

    def get_quote(exchange_id: str) -> dict[str, Decimal | None]:
        ex_class = getattr(ccxt, exchange_id)
        ex = ex_class({"enableRateLimit": True})
        try:
            ex.load_markets()
            symbol = "USDT/USDC" if "USDT/USDC" in ex.symbols else "USDC/USDT"
            ob = ex.fetch_order_book(symbol, limit=5)
            bid = ob["bids"][0][0] if ob.get("bids") else None
            ask = ob["asks"][0][0] if ob.get("asks") else None
            if bid is None or ask is None:
                return {"bid": None, "ask": None, "mid": None}

            bid_d = _safe_decimal(bid)
            ask_d = _safe_decimal(ask)
            mid_d = (bid_d + ask_d) / Decimal(2)

            # Normalize to "USDC per 1 USDT"
            if symbol == "USDC/USDT":
                # price is "USDT per 1 USDC" => invert
                bid_d = (Decimal(1) / bid_d) if bid_d != 0 else None
                ask_d = (Decimal(1) / ask_d) if ask_d != 0 else None
                mid_d = (Decimal(1) / mid_d) if mid_d != 0 else None

            return {"bid": bid_d, "ask": ask_d, "mid": mid_d}
        finally:
            try:
                ex.close()
            except Exception:
                pass

    return {
        "binance": get_quote("binance"),
        "coinbase": get_quote("coinbase"),
    }


def curve_simulate_swap_1m_usdc_to_usdt(w3_eth: Web3, usd_amount: Decimal) -> dict[str, Any]:
    """
    Simulate swapping `usd_amount` USDC -> USDT via Curve 3pool get_dy.

    Returns:
      - dx_usdc, dy_usdt (Decimal, human units)
      - effective_price_usdc_per_usdt (Decimal): USDC / USDT_out
    """
    swap = w3_eth.eth.contract(address=CURVE_3POOL_SWAP, abi=CURVE_SWAP_ABI)

    dx_usdc_raw = int((usd_amount * (Decimal(10) ** USDC_DECIMALS)).to_integral_value(rounding="ROUND_DOWN"))
    dy_usdt_raw: int = swap.functions.get_dy(USDC_INDEX, USDT_INDEX, dx_usdc_raw).call()

    dx_usdc = _from_units(dx_usdc_raw, USDC_DECIMALS)
    dy_usdt = _from_units(dy_usdt_raw, USDT_DECIMALS)
    if dy_usdt == 0:
        price_usdc_per_usdt = None
    else:
        price_usdc_per_usdt = dx_usdc / dy_usdt  # USDC per 1 USDT

    return {
        "dx_usdc": dx_usdc,
        "dy_usdt": dy_usdt,
        "effective_price_usdc_per_usdt": price_usdc_per_usdt,
    }


def basis(curve_price: Decimal | None, cex_mid: Decimal | None) -> Decimal | None:
    if curve_price is None or cex_mid is None or cex_mid == 0:
        return None
    return (curve_price - cex_mid) / cex_mid  # fraction


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

    usd_amount = Decimal("1000000")
    sim = curve_simulate_swap_1m_usdc_to_usdt(w3s["ethereum"], usd_amount=usd_amount)
    curve_px = sim["effective_price_usdc_per_usdt"]
    curve_px_str = "N/A" if curve_px is None else str(curve_px.quantize(Decimal("0.00000001")))

    print()
    print(f"Curve simulated swap (USDC -> USDT) for {usd_amount} USDC:")
    print(f"  USDT out: {sim['dy_usdt']}")
    print(f"  Effective price (USDC per 1 USDT): {curve_px_str}")

    quotes = fetch_cex_top_of_book()
    print()
    print("CEX top-of-book (USDC per 1 USDT):")
    for ex, q in quotes.items():
        bid = q["bid"]
        ask = q["ask"]
        mid = q["mid"]
        if bid is None or ask is None or mid is None:
            print(f"  {ex}: N/A")
            continue
        bps = basis(curve_px, mid)
        bps_str = "N/A" if bps is None else f"{(bps * Decimal(100)).quantize(Decimal('0.0001'))}%"
        print(
            f"  {ex}: bid={bid.quantize(Decimal('0.00000001'))} "
            f"ask={ask.quantize(Decimal('0.00000001'))} "
            f"mid={mid.quantize(Decimal('0.00000001'))} "
            f"basis={bps_str}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
