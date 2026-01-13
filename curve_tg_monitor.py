#!/usr/bin/env python3
"""
Curve 3pool USDT/USDC ratio monitor + Telegram alerts (test-focused).

Requirements (per user request):
- Load ETH_RPC_URL + TELEGRAM_BOT_TOKEN + CHAT_ID (or TELEGRAM_CHAT_ID) from .env
- Read Curve 3pool balances(1)=USDC, balances(2)=USDT (both 6 decimals)
- Compute USDT_Ratio = USDT / (USDC + USDT)
- If ratio > 0.6: send TG warning about discount risk / sell pressure
- If ratio < 0.4: send TG warning about potential USDT premium
- Loop every 60s, print balances each run

Note: To avoid spamming, alerts are sent only when state changes
      (normal->high, normal->low, low/high->normal doesn't alert).
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal
from typing import Any

import requests
from dotenv import load_dotenv
from web3 import Web3


CURVE_3POOL_SWAP = Web3.to_checksum_address("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")
USDC_INDEX = 1
USDT_INDEX = 2
DECIMALS = 6
SIM_USDC_AMOUNT = Decimal("1000000")  # simulate 1,000,000 USDC -> USDT

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
]


def _require(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def _from_units(amount: int, decimals: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** Decimal(decimals))


def tg_send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    r.raise_for_status()


def read_usdc_usdt(w3: Web3) -> tuple[Decimal, Decimal]:
    swap = w3.eth.contract(address=CURVE_3POOL_SWAP, abi=CURVE_SWAP_ABI)
    usdc_raw: int = swap.functions.balances(USDC_INDEX).call()
    usdt_raw: int = swap.functions.balances(USDT_INDEX).call()
    return _from_units(usdc_raw, DECIMALS), _from_units(usdt_raw, DECIMALS)


def curve_price_usdc_per_usdt(w3: Web3, usdc_amount: Decimal) -> Decimal | None:
    """
    Simulate USDC -> USDT via Curve get_dy.
    Returns effective price in USDC per 1 USDT.
    """
    swap = w3.eth.contract(address=CURVE_3POOL_SWAP, abi=CURVE_SWAP_ABI)
    dx_raw = int((usdc_amount * (Decimal(10) ** DECIMALS)).to_integral_value(rounding="ROUND_DOWN"))
    dy_raw: int = swap.functions.get_dy(USDC_INDEX, USDT_INDEX, dx_raw).call()
    dy = _from_units(dy_raw, DECIMALS)
    if dy == 0:
        return None
    return usdc_amount / dy


def compute_usdt_ratio(usdc: Decimal, usdt: Decimal) -> Decimal:
    total = usdc + usdt
    if total == 0:
        return Decimal("0")
    return usdt / total


def main() -> int:
    # Load .env from current directory if present
    load_dotenv(override=False)

    eth_rpc = _require("ETH_RPC_URL")
    tg_token = _require("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID", "").strip() or _require("TELEGRAM_CHAT_ID")

    w3 = Web3(Web3.HTTPProvider(eth_rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise SystemExit("Failed to connect to ETH_RPC_URL")

    print("Starting Curve 3pool monitor (loop=60s)...")
    print(f"  contract={CURVE_3POOL_SWAP}")
    print(f"  chat_id={chat_id}")

    # Track last alert state to avoid spamming
    last_state: str = "normal"  # normal|high|low

    while True:
        try:
            usdc, usdt = read_usdc_usdt(w3)
            ratio = compute_usdt_ratio(usdc, usdt)
            ratio_pct = (ratio * Decimal(100)).quantize(Decimal("0.01"))
            px = curve_price_usdc_per_usdt(w3, SIM_USDC_AMOUNT)
            px_str = "N/A" if px is None else str(px.quantize(Decimal("0.00000001")))

            print(f"USDC={usdc} | USDT={usdt} | USDT_Ratio={ratio_pct}% | CurvePx(USDC/USDT)={px_str}")

            if ratio > Decimal("0.6"):
                if last_state != "high":
                    msg = (
                        "⚠️ Curve 预警：USDT 占比过高，可能折价\n"
                        f"USDC={usdc}\n"
                        f"USDT={usdt}\n"
                        f"USDT_Ratio={ratio_pct}%\n"
                        f"CurvePx(USDC/USDT, {SIM_USDC_AMOUNT} USDC)={px_str}\n"
                        "链上卖压加重！"
                    )
                    tg_send_message(tg_token, chat_id, msg)
                    last_state = "high"
            elif ratio < Decimal("0.4"):
                if last_state != "low":
                    msg = (
                        "⚠️ Curve 预警：USDT 占比过低，可能溢价\n"
                        f"USDC={usdc}\n"
                        f"USDT={usdt}\n"
                        f"USDT_Ratio={ratio_pct}%\n"
                        f"CurvePx(USDC/USDT, {SIM_USDC_AMOUNT} USDC)={px_str}\n"
                        "USDT 可能溢价！"
                    )
                    tg_send_message(tg_token, chat_id, msg)
                    last_state = "low"
            else:
                last_state = "normal"

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)

        time.sleep(60)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)

