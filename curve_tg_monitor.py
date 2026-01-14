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

try:
    import ccxt  # optional (only needed when enabling CEX monitors)
except Exception:  # pragma: no cover
    ccxt = None


# --- Addresses ---
# Ethereum mainnet
CURVE_3POOL_SWAP = Web3.to_checksum_address("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7")
UNIV3_ETH_USDC_USDT_POOL = Web3.to_checksum_address("0x7858E59e0C01EA06Df3aF3D20aC7B0003275D4bF")
ETH_USDC = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
ETH_USDT = Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7")

# Base
#
# NOTE: The Aerodrome USDC/USDT pool address is resolved at runtime via Factory.getPool().
# (Some third-party lists may show non-contract addresses; always verify via eth_getCode.)
AERODROME_FACTORY = Web3.to_checksum_address("0x420DD381B31Aef6683db6B902084cB0FFECe40Da")
BASE_USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
BASE_USDT = Web3.to_checksum_address("0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2")

# Arbitrum
UNIV3_ARB_USDC_USDT_POOL = Web3.to_checksum_address("0xBe38796f97089E4e24Fb598fde52797486572C7C")

# BSC
PANCAKESWAP_STABLE_POOL = Web3.to_checksum_address("0x7EFaEf62fDdCC041262846995661603953569584")

USDC_INDEX = 1  # Curve 3pool: 0=DAI,1=USDC,2=USDT
USDT_INDEX = 2
STABLE_DECIMALS = 6
SIM_USDC_AMOUNT = Decimal("1000000")  # simulate 1,000,000 USDC -> USDT on Curve
BPS_THRESHOLD = Decimal("3")  # 3 bps (arbitrage alert)
DEFAULT_LOOP_SECONDS = 60
DEFAULT_SUMMARY_SECONDS = 3600  # hourly summary push

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

SOLIDLY_FACTORY_ABI: list[dict[str, Any]] = [
    {
        "name": "getPool",
        "outputs": [{"type": "address", "name": "pool"}],
        "inputs": [
            {"type": "address", "name": "tokenA"},
            {"type": "address", "name": "tokenB"},
            {"type": "bool", "name": "stable"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
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
    {
        "name": "symbol",
        "outputs": [{"type": "string", "name": ""}],
        "inputs": [],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "balanceOf",
        "outputs": [{"type": "uint256", "name": ""}],
        "inputs": [{"type": "address", "name": "account"}],
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


def _norm_symbol(sym: str) -> str:
    return sym.strip().upper()


def _classify_stable(sym: str) -> str | None:
    """
    Classify token symbol into buckets we can compare.
    We compare everything as USD-per-USDT (USDC per 1 USDT).
    """
    s = _norm_symbol(sym)
    if s == "USDT":
        return "USDT"
    # treat common USD stables as "USD"
    if s.startswith("USDC") or s in {"USDBC", "BUSD", "DAI", "USD+"}:
        return "USD"
    return None


def _bps_between(cheap: Decimal, expensive: Decimal) -> Decimal:
    if cheap == 0:
        return Decimal("0")
    return ((expensive - cheap) / cheap) * Decimal(10000)


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
    def __init__(
        self,
        eth_rpc_url: str,
        base_rpc_url: str | None,
        bsc_rpc_url: str | None,
        arb_rpc_url: str | None,
    ):
        self.eth = Web3(Web3.HTTPProvider(eth_rpc_url, request_kwargs={"timeout": 20}))
        if not self.eth.is_connected():
            raise SystemExit("Failed to connect to ETH_RPC_URL")
        # More strict: ensure basic RPC methods work
        try:
            self.eth_chain_id = int(self.eth.eth.chain_id)
        except Exception as e:
            raise SystemExit(f"ETH_RPC_URL connected but eth_chainId failed: {e}") from e

        self.base: Web3 | None = None
        if base_rpc_url:
            w3 = Web3(Web3.HTTPProvider(base_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                raise SystemExit("Failed to connect to BASE_RPC_URL")
            try:
                self.base_chain_id = int(w3.eth.chain_id)
            except Exception as e:
                raise SystemExit(f"BASE_RPC_URL connected but eth_chainId failed: {e}") from e
            self.base = w3

        self.bsc: Web3 | None = None
        if bsc_rpc_url:
            w3 = Web3(Web3.HTTPProvider(bsc_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                raise SystemExit("Failed to connect to BSC_RPC_URL")
            try:
                self.bsc_chain_id = int(w3.eth.chain_id)
            except Exception as e:
                raise SystemExit(f"BSC_RPC_URL connected but eth_chainId failed: {e}") from e
            self.bsc = w3

        self.arb: Web3 | None = None
        if arb_rpc_url:
            w3 = Web3(Web3.HTTPProvider(arb_rpc_url, request_kwargs={"timeout": 20}))
            if not w3.is_connected():
                raise SystemExit("Failed to connect to ARB_RPC_URL")
            try:
                self.arb_chain_id = int(w3.eth.chain_id)
            except Exception as e:
                raise SystemExit(f"ARB_RPC_URL connected but eth_chainId failed: {e}") from e
            self.arb = w3


class PoolMonitor:
    name: str
    chain: str

    def fetch(self) -> PricePoint:
        raise NotImplementedError


class CexTopOfBookMonitor(PoolMonitor):
    chain = "cex"

    def __init__(self, exchange_id: str):
        if ccxt is None:
            raise RuntimeError("ccxt is not installed; install requirements.txt to enable CEX monitors")
        self.name = exchange_id
        self._exchange_id = exchange_id

    def fetch(self) -> PricePoint:
        ex_class = getattr(ccxt, self._exchange_id)
        ex = ex_class({"enableRateLimit": True})
        try:
            ex.load_markets()
            symbol = "USDT/USDC" if "USDT/USDC" in ex.symbols else "USDC/USDT"
            ob = ex.fetch_order_book(symbol, limit=5)
            bid = ob["bids"][0][0] if ob.get("bids") else None
            ask = ob["asks"][0][0] if ob.get("asks") else None
            if bid is None or ask is None:
                raise RuntimeError("empty orderbook")
            bid_d = Decimal(str(bid))
            ask_d = Decimal(str(ask))
            mid = (bid_d + ask_d) / Decimal(2)

            # Normalize to USDC per 1 USDT
            if symbol == "USDC/USDT":
                mid = (Decimal(1) / mid) if mid != 0 else Decimal("0")

            return PricePoint(
                name=self.name,
                chain=self.chain,
                price_usdc_per_usdt=mid,
                meta={"symbol": symbol, "bid": bid_d, "ask": ask_d},
            )
        finally:
            try:
                ex.close()
            except Exception:
                pass


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
        self.factory = self.w3.eth.contract(address=AERODROME_FACTORY, abi=SOLIDLY_FACTORY_ABI)
        self._pool: str | None = None

    def _resolve_pool(self) -> str:
        if self._pool:
            return self._pool
        pool = Web3.to_checksum_address(self.factory.functions.getPool(BASE_USDC, BASE_USDT, True).call())
        if int(pool, 16) == 0:
            raise RuntimeError("aerodrome factory getPool returned zero address for USDC/USDT stable")
        self._pool = pool
        return pool

    def fetch(self) -> PricePoint:
        pool_addr = self._resolve_pool()
        self.pair = self.w3.eth.contract(address=pool_addr, abi=PAIR_ABI)

        step = "get_code"
        try:
            code = self.w3.eth.get_code(pool_addr)
        except Exception as e:
            raise RuntimeError(f"aerodrome fetch failed at {step}: {e}") from e
        if not code or code == b"":
            raise RuntimeError("aerodrome fetch failed: no contract code at resolved pool address")

        step = "token0/token1"
        try:
            token0 = Web3.to_checksum_address(self.pair.functions.token0().call())
            token1 = Web3.to_checksum_address(self.pair.functions.token1().call())
        except Exception as e:
            raise RuntimeError(f"aerodrome fetch failed at {step}: {e}") from e

        # Aerodrome pools are usually UniswapV2-like, but keep a fallback.
        step = "getReserves"
        try:
            r0, r1, _ = self.pair.functions.getReserves().call()
        except Exception:
            step = "balances(0/1)"
            try:
                r0 = int(self.pair.functions.balances(0).call())
                r1 = int(self.pair.functions.balances(1).call())
            except Exception as e:
                raise RuntimeError(f"aerodrome fetch failed at {step}: {e}") from e

        # Prefer address mapping to avoid token symbol edge-cases.
        if token0 == BASE_USDC and token1 == BASE_USDT:
            usd_amt = _from_units(int(r0), STABLE_DECIMALS)
            usdt_amt = _from_units(int(r1), STABLE_DECIMALS)
            sym0, sym1 = "USDC", "USDT"
        elif token0 == BASE_USDT and token1 == BASE_USDC:
            usdt_amt = _from_units(int(r0), STABLE_DECIMALS)
            usd_amt = _from_units(int(r1), STABLE_DECIMALS)
            sym0, sym1 = "USDT", "USDC"
        else:
            # Fallback: Use token decimals/symbols to map into USD per USDT.
            step = "token metadata"
            try:
                t0 = self.w3.eth.contract(address=token0, abi=ERC20_ABI)
                t1 = self.w3.eth.contract(address=token1, abi=ERC20_ABI)
                dec0 = int(t0.functions.decimals().call())
                dec1 = int(t1.functions.decimals().call())
                sym0 = str(t0.functions.symbol().call())
                sym1 = str(t1.functions.symbol().call())
            except Exception as e:
                raise RuntimeError(f"aerodrome fetch failed at {step}: {e}") from e

            amt0 = _from_units(int(r0), dec0)
            amt1 = _from_units(int(r1), dec1)

            c0 = _classify_stable(sym0)
            c1 = _classify_stable(sym1)
            if c0 == "USDT" and c1 == "USD":
                usdt_amt, usd_amt = amt0, amt1
            elif c0 == "USD" and c1 == "USDT":
                usdt_amt, usd_amt = amt1, amt0
            else:
                raise RuntimeError(f"unexpected tokens: {sym0}/{sym1}")

        price = (usd_amt / usdt_amt) if usdt_amt != 0 else Decimal("0")  # USDC per 1 USDT
        total = usd_amt + usdt_amt
        usdt_ratio = (usdt_amt / total) if total != 0 else Decimal("0")

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price,
            meta={
                "usd": usd_amt,
                "usdt": usdt_amt,
                "usdt_ratio": usdt_ratio,
                "pool": pool_addr,
                "token0": token0,
                "token1": token1,
                "symbol0": sym0,
                "symbol1": sym1,
            },
        )


class PancakeSwapV2StablePoolMonitor(PoolMonitor):
    name = "pancakeswap-stable"
    chain = "bsc"

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.pair = self.w3.eth.contract(address=PANCAKESWAP_STABLE_POOL, abi=PAIR_ABI)

    def fetch(self) -> PricePoint:
        token0 = Web3.to_checksum_address(self.pair.functions.token0().call())
        token1 = Web3.to_checksum_address(self.pair.functions.token1().call())
        r0, r1, _ = self.pair.functions.getReserves().call()

        t0 = self.w3.eth.contract(address=token0, abi=ERC20_ABI)
        t1 = self.w3.eth.contract(address=token1, abi=ERC20_ABI)
        dec0 = int(t0.functions.decimals().call())
        dec1 = int(t1.functions.decimals().call())
        sym0 = str(t0.functions.symbol().call())
        sym1 = str(t1.functions.symbol().call())

        amt0 = _from_units(int(r0), dec0)
        amt1 = _from_units(int(r1), dec1)

        c0 = _classify_stable(sym0)
        c1 = _classify_stable(sym1)
        if c0 == "USDT" and c1 == "USD":
            price = (amt1 / amt0) if amt0 != 0 else Decimal("0")
        elif c0 == "USD" and c1 == "USDT":
            price = (amt0 / amt1) if amt1 != 0 else Decimal("0")
        else:
            raise RuntimeError(f"unexpected tokens: {sym0}/{sym1}")

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price,
            meta={"token0": token0, "token1": token1, "symbol0": sym0, "symbol1": sym1},
        )


class UniswapV3StablePoolMonitor(PoolMonitor):
    def __init__(self, *, w3: Web3, pool_address: str, chain: str, name: str):
        self.chain = chain
        self.name = name
        self.w3 = w3
        self.pool_address = Web3.to_checksum_address(pool_address)
        self.pool = self.w3.eth.contract(address=self.pool_address, abi=UNIV3_POOL_ABI)
        self._token0: str | None = None
        self._token1: str | None = None
        self._dec0: int | None = None
        self._dec1: int | None = None
        self._sym0: str | None = None
        self._sym1: str | None = None

    def _load_tokens(self) -> None:
        if (
            self._token0
            and self._token1
            and self._dec0 is not None
            and self._dec1 is not None
            and self._sym0 is not None
            and self._sym1 is not None
        ):
            return
        t0 = Web3.to_checksum_address(self.pool.functions.token0().call())
        t1 = Web3.to_checksum_address(self.pool.functions.token1().call())
        c0 = self.w3.eth.contract(address=t0, abi=ERC20_ABI)
        c1 = self.w3.eth.contract(address=t1, abi=ERC20_ABI)
        d0 = int(c0.functions.decimals().call())
        d1 = int(c1.functions.decimals().call())
        s0 = str(c0.functions.symbol().call())
        s1 = str(c1.functions.symbol().call())
        self._token0, self._token1, self._dec0, self._dec1, self._sym0, self._sym1 = t0, t1, d0, d1, s0, s1

    def fetch(self) -> PricePoint:
        self._load_tokens()
        assert (
            self._token0
            and self._token1
            and self._dec0 is not None
            and self._dec1 is not None
            and self._sym0 is not None
            and self._sym1 is not None
        )

        sqrt_price_x96 = int(self.pool.functions.slot0().call()[0])

        # Uniswap V3: price token1 per token0 = (sqrtP^2 / 2^192) * 10^(dec0-dec1)
        numerator = Decimal(sqrt_price_x96) ** 2
        denom = Decimal(2) ** 192
        price_1_per_0 = (numerator / denom) * (Decimal(10) ** Decimal(self._dec0 - self._dec1))

        c0 = _classify_stable(self._sym0)
        c1 = _classify_stable(self._sym1)
        if c0 == "USDT" and c1 == "USD":
            price_usdc_per_usdt = price_1_per_0
        elif c0 == "USD" and c1 == "USDT":
            price_usdc_per_usdt = (Decimal(1) / price_1_per_0) if price_1_per_0 != 0 else Decimal("0")
        else:
            raise RuntimeError(f"unexpected tokens: {self._sym0}/{self._sym1}")

        # "Reserves" approximation: actual token balances held by the pool contract.
        c0_contract = self.w3.eth.contract(address=self._token0, abi=ERC20_ABI)
        c1_contract = self.w3.eth.contract(address=self._token1, abi=ERC20_ABI)
        bal0_raw = int(c0_contract.functions.balanceOf(self.pool_address).call())
        bal1_raw = int(c1_contract.functions.balanceOf(self.pool_address).call())
        bal0 = _from_units(bal0_raw, int(self._dec0))
        bal1 = _from_units(bal1_raw, int(self._dec1))

        if c0 == "USDT" and c1 == "USD":
            usdt_amt, usd_amt = bal0, bal1
        else:
            # c0 == USD and c1 == USDT
            usd_amt, usdt_amt = bal0, bal1
        total = usd_amt + usdt_amt
        usdt_ratio = (usdt_amt / total) if total != 0 else Decimal("0")

        return PricePoint(
            name=self.name,
            chain=self.chain,
            price_usdc_per_usdt=price_usdc_per_usdt,
            meta={
                "sqrtPriceX96": sqrt_price_x96,
                "token0": self._token0,
                "token1": self._token1,
                "symbol0": self._sym0,
                "symbol1": self._sym1,
                "decimals0": self._dec0,
                "decimals1": self._dec1,
                "usd": usd_amt,
                "usdt": usdt_amt,
                "usdt_ratio": usdt_ratio,
            },
        )


class ArbitrageDetector:
    def __init__(self, notifier: TelegramNotifier, bps_threshold: Decimal):
        self.notifier = notifier
        self.bps_threshold = bps_threshold
        self._last_key: str | None = None
        self._last_sent_ts: float = 0.0
        self.cooldown_seconds = 300  # avoid spam

    def evaluate_and_alert(self, points: list[PricePoint]) -> None:
        points = [p for p in points if p.price_usdc_per_usdt is not None and p.price_usdc_per_usdt > 0]
        if len(points) < 2:
            return
        points_sorted = sorted(points, key=lambda p: p.price_usdc_per_usdt)
        cheap = points_sorted[0]
        expensive = points_sorted[-1]

        spread_bps = _bps_between(cheap.price_usdc_per_usdt, expensive.price_usdc_per_usdt)
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


class SummaryPublisher:
    def __init__(self, notifier: TelegramNotifier, interval_seconds: int):
        self.notifier = notifier
        self.interval_seconds = max(60, int(interval_seconds))
        self._last_sent_ts: float = 0.0

    def maybe_send(self, points: list[PricePoint]) -> None:
        now = time.time()
        if self._last_sent_ts and (now - self._last_sent_ts) < self.interval_seconds:
            return

        # Expect Curve + Uniswap; send what we have.
        by_name = {f"{p.chain}/{p.name}": p for p in points}
        curve = by_name.get("ethereum/curve-3pool")
        uni = by_name.get("ethereum/uniswapv3-eth-usdc-usdt")

        lines = [f"📊 USDT/USDC 链上监控（每小时汇总）", f"time={_utc_ts()}"]
        if curve:
            ratio_pct = (Decimal(str(curve.meta.get("usdt_ratio", 0))) * Decimal(100)).quantize(Decimal("0.01"))
            lines.append(
                f"Curve: px={curve.price_usdc_per_usdt.quantize(Decimal('0.00000001'))} USDC/USDT | USDT_Ratio={ratio_pct}%"
            )
        else:
            lines.append("Curve: N/A")

        if uni:
            ratio_pct = (Decimal(str(uni.meta.get("usdt_ratio", 0))) * Decimal(100)).quantize(Decimal("0.01"))
            lines.append(
                f"UniswapV3: px={uni.price_usdc_per_usdt.quantize(Decimal('0.00000001'))} USDC/USDT | USDT_Ratio={ratio_pct}%"
            )
        else:
            lines.append("UniswapV3: N/A")

        if curve and uni:
            cheap = min(curve.price_usdc_per_usdt, uni.price_usdc_per_usdt)
            expensive = max(curve.price_usdc_per_usdt, uni.price_usdc_per_usdt)
            spread_bps = _bps_between(cheap, expensive).quantize(Decimal("0.1"))
            lines.append(f"Spread(Curve vs UniV3)={spread_bps}bps")

        self.notifier.send("\n".join(lines))
        self._last_sent_ts = now


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Monitor Curve/Aerodrome/UniswapV3 USDT/USDC and alert on spreads.")
    p.add_argument("--once", action="store_true", help="Run one iteration and exit")
    p.add_argument("--interval-seconds", type=int, default=DEFAULT_LOOP_SECONDS, help="Loop interval seconds (default: 60)")
    p.add_argument("--bps-threshold", default=str(BPS_THRESHOLD), help="Alert threshold in bps (default: 3)")
    p.add_argument(
        "--summary-seconds",
        type=int,
        default=DEFAULT_SUMMARY_SECONDS,
        help="Summary push interval seconds (default: 3600)",
    )
    return p.parse_args()


def main() -> int:
    # Load .env from current directory if present
    load_dotenv(override=False)
    args = _parse_args()

    eth_rpc = _require("ETH_RPC_URL")
    base_rpc = os.getenv("BASE_RPC_URL", "").strip() or None
    bsc_rpc = os.getenv("BSC_RPC_URL", "").strip() or None
    arb_rpc = os.getenv("ARB_RPC_URL", "").strip() or None
    tg_token = _require("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID", "").strip() or _require("TELEGRAM_CHAT_ID")

    providers = Web3Providers(eth_rpc_url=eth_rpc, base_rpc_url=base_rpc, bsc_rpc_url=bsc_rpc, arb_rpc_url=arb_rpc)
    notifier = TelegramNotifier(bot_token=tg_token, chat_id=chat_id)
    detector = ArbitrageDetector(notifier=notifier, bps_threshold=Decimal(str(args.bps_threshold)))
    summary = SummaryPublisher(notifier=notifier, interval_seconds=args.summary_seconds)

    monitors: list[PoolMonitor] = [
        Curve3PoolMonitor(providers.eth),
        UniswapV3StablePoolMonitor(
            w3=providers.eth,
            pool_address=str(UNIV3_ETH_USDC_USDT_POOL),
            chain="ethereum",
            name="uniswapv3-eth-usdc-usdt",
        ),
    ]
    # Per request: disable Aerodrome/Base for now; keep only Curve + UniswapV3.

    print("Starting multi-pool monitor (loop=60s)...")
    print(f"  tg_chat_id={chat_id}")
    print(f"  curve={CURVE_3POOL_SWAP}")
    print(f"  univ3_eth={UNIV3_ETH_USDC_USDT_POOL}")
    print(f"  bsc=({'on' if providers.bsc else 'off'}) arb=({'on' if providers.arb else 'off'})")
    # Helpful for diagnosing RPC misconfiguration
    print(f"  eth_chain_id={getattr(providers, 'eth_chain_id', 'unknown')}")

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
            summary.maybe_send(points)

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

