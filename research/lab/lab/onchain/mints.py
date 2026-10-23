"""The coins the on-chain paper book can hold, as SPL tokens, and the exchange coin each stands for.

Every mint was checked on 2026-10-23 against Jupiter's token list
(lite-api.jup.ag/tokens/v2, tag "verified"; symbol and decimals as listed there)
and, where the coin is old enough to be in it, the Solana Labs token list
(github.com/solana-labs/token-list). A coin without a mint from such a source is
left out, not guessed. Out on purpose: NEAR, SUI, DOGE, XRP, ADA, AVAX, LINK,
LTC, DOT, BCH, PEPE, SHIB and the other coins the crypto books trade that have no
established, deep SPL version; a target on one of them stays cash here.

`coin` is the engine's coin (crypto:<coin>/USD on Kraken), `alpaca` whether the
Alpaca account lists the same coin (lab.universe.ALPACA).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mint:
    coin: str          # the engine's coin, what the books' weights name
    symbol: str        # the SPL token's symbol as its listing gives it
    mint: str
    decimals: int
    kraken: str        # the Kraken pair it stands for
    alpaca: str | None  # the Alpaca pair, None when Alpaca does not list the coin
    source: str        # where the mint was checked


JUP = "Jupiter verified list"
BOTH = "Jupiter verified list, Solana Labs token list"

USDC = Mint("USDC", "USDC", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 6, "USDC/USD", "USDC/USD", BOTH)
SOL = Mint("SOL", "SOL", "So11111111111111111111111111111111111111112", 9, "SOL/USD", "SOL/USD", BOTH)

COINS: dict[str, Mint] = {m.coin: m for m in (
    SOL,
    # Coinbase's own BTC on Solana; Wormhole's WBTC (3NZ9JMVB...) is as deep but bridged.
    Mint("BTC", "cbBTC", "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", 8, "BTC/USD", "BTC/USD", JUP),
    Mint("ETH", "WETH", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs", 8, "ETH/USD", "ETH/USD", BOTH),
    Mint("JUP", "JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", 6, "JUP/USD", None, JUP),
    Mint("BONK", "Bonk", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", 5, "BONK/USD", "BONK/USD", JUP),
    Mint("WIF", "$WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", 6, "WIF/USD", "WIF/USD", JUP),
    Mint("POPCAT", "POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", 9, "POPCAT/USD", None, JUP),
    Mint("RAY", "RAY", "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", 6, "RAY/USD", None, BOTH),
    Mint("PYTH", "PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", 6, "PYTH/USD", None, JUP),
    Mint("JTO", "JTO", "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL", 9, "JTO/USD", None, JUP),
    Mint("RENDER", "RENDER", "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof", 8, "RENDER/USD", "RENDER/USD", JUP),
    Mint("TRUMP", "TRUMP", "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN", 6, "TRUMP/USD", "TRUMP/USD", JUP),
)}
BY_MINT: dict[str, Mint] = {m.mint: m for m in (USDC, *COINS.values())}


def raw(m: Mint, amount: float) -> int:
    """UI amount to the token's integer units, rounded down (a swap never spends more than it has)."""
    return max(int(amount * 10 ** m.decimals + 1e-6), 0)


def ui(m: Mint, amount: int) -> float:
    return amount / 10 ** m.decimals
