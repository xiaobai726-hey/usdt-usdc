#!/usr/bin/env python3
"""
Multi-pool USDT/USDC monitor (Ethereum + Base) + Telegram alerts.

Pools:
- Curve 3pool (Ethereum): balances + get_dy simulated price
- Aerodrome stable pool (Base): getReserves() indicative price
- Uniswap V3 pool (Ethereum): slot0 price (more sensitive)

Alert:
- If max/min price difference > 3bps, send TG message:
  "💡 发现链上套利/最优兑换路径：[A] 比 [B] 便宜 5bps"
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import sys
import time
from decimal import Decimal
from typing import Any

import requests
from dotenv import load_dotenv
from web3 import Web3


# --- Addresses ---
# Ethereum mainnet
CURVE_3POOL_SWAP = Web3.to_checksum_address("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")
UNIV3_USDC_USDT_POOL = Web3.to_checksum_address("0x7858E59e0C01EA06Df3aF3D20aC7B0003275D4bF")
ETH_USDC = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
ETH_USDT = Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7")

# Base
AERODROME_USDC_USDT_POOL = Web3.to_checksum_address("0x6cD36619DAf209e5730815E2811F4501D92c026b")
BASE_USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
BASE_USDT = Web3.to_checksum_address("0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2")

USDC_INDEX = 1  # Curve 3pool: 0=DAI,1=USDC,2=USDT
USDT_INDEX = 2
STABLE_DECIMALS = 6
SIM_USDC_AMOUNT = Decimal("1000000")  # simulate 1,000,000 USDC -> USDT on Curve
BPS_THRESHOLD = Decimal("3")  # 3 bps
DEFAULT_LOOP_SECONDS = 60

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

PAIR_ABI: list[dict[str, Any]] = [
    {
        "name": "getReserves",
        "outputs": [
            {"type": "uint112", "name": "_reserve0"},
            {"type": "uint112", "name": "_reserve1"},
            {"type": "uint32", "name": "_blockTimestampLast"},
        ],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "balances",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [{"type": "uint256", "name": "i"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "token0",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "token1",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
]

UNIV3_POOL_ABI: list[dict[str, Any]] = [
    {
        "name": "slot0",
        "outputs": [
            {"type": "uint160", "name": "sqrtPriceX96"},
            {"type": "int24", "name": "tick"},
            {"type": "uint16", "name": "observationIndex"},
            {"type": "uint16", "name": "observationCardinality"},
            {"type": "uint16", "name": "observationCardinalityNext"},
            {"type": "uint8", "name": "feeProtocol"},
            {"type": "bool", "name": "unlocked"},
        ],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "token0",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "token1",
        "outputs": [{"type": "address", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI: list[dict[str, Any]] = [
    {
        "name": "decimals",
        "outputs": [{"type": "uint8", "name": ""}],
        "inputs": [],
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


def _utc_ts() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds")


@dataclasses.dataclass(frozen=True)
class PricePoint:
    name: str
    chain: str
    price_usdc_per_usdt: Decimal
    meta: dict[str, Any]


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        r = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=15)
        r.raise_for_status()


class Web3Providers:
    def __init__(self, eth_rpc_url: str, base_rpc_url: str | None, bsc_rpc_url: str | None):
        self.eth = Web3(Web3.HTTPProvider(eth_rpc_url, request_kwargs={"timeout": 20}))
        if not self.eth.is_connected():
            raise SystemExit("Failed to connect to ETH_RPC_URL")

        self.base: Web3 | None = None
        if base_rpc_url:
            w3 = Web3(Web3.HTTPProvider(base_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                raise SystemExit("Failed to connect to BASE_RPC_URL")
            self.base = w3

        self.bsc: Web3 | None = None
        if bsc_rpc_url:
            w3 = Web3(Web3.HTTPProvider(bsc_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                raise SystemExit("Failed to connect to BSC_RPC_URL")
            self.bsc = w3


class PoolMonitor:
    name: str
    chain: str

    def fetch(self) -> PricePoint:
        raise NotImplementedError


class Curve3PoolMonitor(PoolMonitor):
    name = "curve-3pool"
    chain = "ethereum"

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.swap = self.w3.eth.contract(address=CURVE_3POOL_SWAP, abi=CURVE_SWAP_ABI)

    def fetch(self) -> PricePoint:
        usdc_raw: int = self.swap.functions.balances(USDC_INDEX).call()
        usdt_raw: int = self.swap.functions.balances(USDT_INDEX).call()
        usdc = _from_units(usdc_raw, STABLE_DECIMALS)
        usdt = _from_units(usdt_raw, STABLE_DECIMALS)
        total = usdc + usdt
        usdt_ratio = (usdt / total) if total != 0 else Decimal("0")

        # price via get_dy (USDC -> USDT)
        dx_raw = int((SIM_USDC_AMOUNT * (Decimal(10) ** STABLE_DECIMALS)).to_integral_value(rounding="ROUND_DOWN"))
        dy_raw: int = self.swap.functions.get_dy(USDC_INDEX, USDT_INDEX, dx_raw).call()
        dy = _from_units(dy_raw, STABLE_DECIMALS)
        price = (SIM_USDC_AMOUNT / dy) if dy != 0 else Decimal("0")

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price,
            meta={
                "usdc": usdc,
                "usdt": usdt,
                "usdt_ratio": usdt_ratio,
                "sim_usdc_amount": SIM_USDC_AMOUNT,
                "sim_usdt_out": dy,
            },
        )


class AerodromeStablePoolMonitor(PoolMonitor):
    name = "aerodrome-usdc-usdt"
    chain = "base"

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.pair = self.w3.eth.contract(address=AERODROME_USDC_USDT_POOL, abi=PAIR_ABI)

    def fetch(self) -> PricePoint:
        token0 = Web3.to_checksum_address(self.pair.functions.token0().call())
        token1 = Web3.to_checksum_address(self.pair.functions.token1().call())

        # Aerodrome pools are usually UniswapV2-like, but keep a fallback.
        try:
            r0, r1, _ = self.pair.functions.getReserves().call()
        except Exception:
            # best-effort fallback: balances(0/1)
            r0 = int(self.pair.functions.balances(0).call())
            r1 = int(self.pair.functions.balances(1).call())

        # Map reserves to USDC/USDT (both assumed 6 decimals on Base)
        if token0 == BASE_USDC and token1 == BASE_USDT:
            usdc = _from_units(int(r0), STABLE_DECIMALS)
            usdt = _from_units(int(r1), STABLE_DECIMALS)
        elif token0 == BASE_USDT and token1 == BASE_USDC:
            usdt = _from_units(int(r0), STABLE_DECIMALS)
            usdc = _from_units(int(r1), STABLE_DECIMALS)
        else:
            # Fallback: treat token0 as USDC, token1 as USDT (best-effort)
            usdc = _from_units(int(r0), STABLE_DECIMALS)
            usdt = _from_units(int(r1), STABLE_DECIMALS)

        total = usdc + usdt
        usdt_ratio = (usdt / total) if total != 0 else Decimal("0")
        price = (usdc / usdt) if usdt != 0 else Decimal("0")  # indicative: USDC per 1 USDT

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price,
            meta={
                "usdc": usdc,
                "usdt": usdt,
                "usdt_ratio": usdt_ratio,
                "token0": token0,
                "token1": token1,
            },
        )


class UniswapV3PoolMonitor(PoolMonitor):
    name = "uniswapv3-usdc-usdt"
    chain = "ethereum"

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.pool = self.w3.eth.contract(address=UNIV3_USDC_USDT_POOL, abi=UNIV3_POOL_ABI)
        self._token0: str | None = None
        self._token1: str | None = None
        self._dec0: int | None = None
        self._dec1: int | None = None

    def _load_tokens(self) -> None:
        if self._token0 and self._token1 and self._dec0 is not None and self._dec1 is not None:
            return
        t0 = Web3.to_checksum_address(self.pool.functions.token0().call())
        t1 = Web3.to_checksum_address(self.pool.functions.token1().call())
        d0 = int(self.w3.eth.contract(address=t0, abi=ERC20_ABI).functions.decimals().call())
        d1 = int(self.w3.eth.contract(address=t1, abi=ERC20_ABI).functions.decimals().call())
        self._token0, self._token1, self._dec0, self._dec1 = t0, t1, d0, d1

    def fetch(self) -> PricePoint:
        self._load_tokens()
        assert self._token0 and self._token1 and self._dec0 is not None and self._dec1 is not None
        sqrt_price_x96 = int(self.pool.functions.slot0().call()[0])

        # Uniswap V3: price token1 per token0 = (sqrtP^2 / 2^192) * 10^(dec0-dec1)
        numerator = Decimal(sqrt_price_x96) ** 2
        denom = Decimal(2) ** 192
        price_1_per_0 = (numerator / denom) * (Decimal(10) ** Decimal(self._dec0 - self._dec1))

        # Normalize to USDC per 1 USDT
        if self._token0 == ETH_USDC and self._token1 == ETH_USDT:
            # token1/token0 = USDT per USDC => invert for USDC per USDT
            price_usdc_per_usdt = (Decimal(1) / price_1_per_0) if price_1_per_0 != 0 else Decimal("0")
        elif self._token0 == ETH_USDT and self._token1 == ETH_USDC:
            # token1/token0 = USDC per USDT
            price_usdc_per_usdt = price_1_per_0
        else:
            # Best-effort: assume token1 is USDT and token0 is USDC and invert like above
            price_usdc_per_usdt = (Decimal(1) / price_1_per_0) if price_1_per_0 != 0 else Decimal("0")

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price_usdc_per_usdt,
            meta={
                "sqrtPriceX96": sqrt_price_x96,
                "token0": self._token0,
                "token1": self._token1,
                "decimals0": self._dec0,
                "decimals1": self._dec1,
            },
        )


class ArbitrageDetector:
    def __init__(self, notifier: TelegramNotifier, bps_threshold: Decimal):
        self.notifier = notifier
        self.bps_threshold = bps_threshold
        self._last_key: str | None = None
        self._last_sent_ts: float = 0.0
        self.cooldown_seconds = 300  # avoid spam

    @staticmethod
    def _spread_bps(min_p: Decimal, max_p: Decimal) -> Decimal:
        if min_p == 0:
            return Decimal("0")
        return ((max_p - min_p) / min_p) * Decimal(10000)

    def evaluate_and_alert(self, points: list[PricePoint]) -> None:
        if len(points) < 2:
            return
        points_sorted = sorted(points, key=lambda p: p.price_usdc_per_usdt)
        cheap = points_sorted[0]
        expensive = points_sorted[-1]

        spread_bps = self._spread_bps(cheap.price_usdc_per_usdt, expensive.price_usdc_per_usdt)
        if spread_bps < self.bps_threshold:
            self._last_key = None
            return

        key = f"{cheap.chain}:{cheap.name}->{expensive.chain}:{expensive.name}"
        now = time.time()
        if self._last_key == key and (now - self._last_sent_ts) < self.cooldown_seconds:
            return

        msg = (
            f"💡 发现链上套利/最优兑换路径：[{cheap.chain}/{cheap.name}] 比 "
            f"[{expensive.chain}/{expensive.name}] 便宜 {spread_bps.quantize(Decimal('0.1'))}bps\n"
            f"time={_utc_ts()}\n"
            f"cheap_price(USDC/USDT)={cheap.price_usdc_per_usdt.quantize(Decimal('0.00000001'))}\n"
            f"expensive_price(USDC/USDT)={expensive.price_usdc_per_usdt.quantize(Decimal('0.00000001'))}"
        )
        self.notifier.send(msg)
        self._last_key = key
        self._last_sent_ts = now


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Monitor Curve/Aerodrome/UniswapV3 USDT/USDC and alert on spreads.")
    p.add_argument("--once", action="store_true", help="Run one iteration and exit")
    p.add_argument("--interval-seconds", type=int, default=DEFAULT_LOOP_SECONDS, help="Loop interval seconds (default: 60)")
    p.add_argument("--bps-threshold", default=str(BPS_THRESHOLD), help="Alert threshold in bps (default: 3)")
    return p.parse_args()


def main() -> int:
    # Load .env from current directory if present
    load_dotenv(override=False)
    args = _parse_args()

    eth_rpc = _require("ETH_RPC_URL")
    base_rpc = os.getenv("BASE_RPC_URL", "").strip() or None
    bsc_rpc = os.getenv("BSC_RPC_URL", "").strip() or None
    tg_token = _require("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID", "").strip() or _require("TELEGRAM_CHAT_ID")

    providers = Web3Providers(eth_rpc_url=eth_rpc, base_rpc_url=base_rpc, bsc_rpc_url=bsc_rpc)
    notifier = TelegramNotifier(bot_token=tg_token, chat_id=chat_id)
    detector = ArbitrageDetector(notifier=notifier, bps_threshold=Decimal(str(args.bps_threshold)))

    monitors: list[PoolMonitor] = [
        Curve3PoolMonitor(providers.eth),
        UniswapV3PoolMonitor(providers.eth),
    ]
    if providers.base is not None:
        monitors.append(AerodromeStablePoolMonitor(providers.base))
    else:
        print("BASE_RPC_URL not set; skipping Aerodrome(Base) monitor.", file=sys.stderr)
    if providers.bsc is None:
        print("BSC_RPC_URL not set; skipping BSC monitors.", file=sys.stderr)

    print("Starting multi-pool monitor (loop=60s)...")
    print(f"  tg_chat_id={chat_id}")
    print(f"  curve={CURVE_3POOL_SWAP}")
    print(f"  univ3={UNIV3_USDC_USDT_POOL}")
    print(f"  aerodrome={AERODROME_USDC_USDT_POOL} (base={'on' if providers.base else 'off'})")
    print(f"  bsc=({'on' if providers.bsc else 'off'})")

    while True:
        try:
            points: list[PricePoint] = []
            for m in monitors:
                try:
                    p = m.fetch()
                    points.append(p)
                except Exception as e:
                    print(f"Error fetching {m.chain}/{m.name}: {e}", file=sys.stderr)

            for p in points:
                px = p.price_usdc_per_usdt.quantize(Decimal("0.00000001"))
                extra = ""
                if "usdt_ratio" in p.meta:
                    ratio_pct = (Decimal(str(p.meta["usdt_ratio"])) * Decimal(100)).quantize(Decimal("0.01"))
                    extra = f" | USDT_Ratio={ratio_pct}%"
                print(f"[{p.chain}/{p.name}] price(USDC/USDT)={px}{extra}")

            detector.evaluate_and_alert(points)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)

        if args.once:
            return 0
        time.sleep(max(1, int(args.interval_seconds)))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)

