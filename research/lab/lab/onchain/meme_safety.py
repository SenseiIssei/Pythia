"""The per-coin safety check of the meme module: whether a memecoin may be quoted, paper-traded or ever traded.

Read only: no key, nothing signed or sent. docs/ONCHAIN-MEME.md. A coin passes only when ALL hold:

  mint        the mint account exists under the classic Token program (Token-2022 refused, as the
              guard does; its extensions are named in the reason: transfer fee, transfer hook,
              permanent delegate, ...), is initialised, has no mint authority and no freeze authority
              (unless the mint is on the owner's exception list, EXCEPTION_PATHS: it lifts those two
              checks only)
  pool        its best pool on Raydium (LaunchLab included), Meteora (its dynamic bonding curve
              included), Orca or PumpSwap (DexScreener's pairs; never pump.fun's own curve) holds at
              least MIN_LIQUIDITY_USD
  holders     the 10 largest holders (getTokenLargestAccounts), minus pools and program vaults (an
              owner off the ed25519 curve or a pool address) and burn addresses, hold under
              MAX_TOP10_SHARE of the supply outside the burn addresses; without that read, Jupiter's
              audit share (topHoldersPercentage) stands in, and with neither the coin is refused
  age         its first pool is at least MIN_AGE_MS old (DexScreener's pairCreatedAt, else Jupiter's
              firstPool.createdAt)
  block list  neither the mint nor its creator is on the owner's block list (the pump.fun bot's:
              /etc/pythia/blocked-mints.txt and <data>/pumpfun_rt/blocked-mints.txt, one mint per
              line, "creator:<address>" for a creator); the creators are Jupiter's `dev`, the Metaplex
              metadata's update authority and its creators

Jupiter's token API (tokens/v2/search) adds its verified and strict tags, organic score, liquidity and
holder count to the verdict's facts, for the report; they decide nothing on their own. Every refusal has
a plain reason. The verdict per mint is cached with its time in <data>/onchain/meme/safety.json; the live
path asks for one from the last minute (live_gate.meme_problems), the paper books accept PAPER_MAX_AGE_MS.

    python -m lab.onchain.meme_safety <mint> [<mint> ...]     check and print, writes the cache
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ..pumpfun_rt import txbuild as X
from ..pumpfun_rt.events import WSOL, b58

MIN_LIQUIDITY_USD = 20_000.0
MAX_TOP10_SHARE = 0.30
MIN_AGE_MS = 5 * 60_000
PAPER_MAX_AGE_MS = 10 * 60_000
METADATA_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
BURN = frozenset({"1nc1nerator11111111111111111111111111111111", X.SYSTEM})
# DexScreener's dexId of the venues we trade through Jupiter; pump.fun's own curve ("pumpfun") is not one.
DEXES = ("raydium", "launchlab", "letsbonk", "meteora", "orca", "pumpswap")
DEX_URL = "https://api.dexscreener.com/tokens/v1/solana/"
# Token-2022 extension types (spl-token-2022 ExtensionType), to say why such a mint is refused.
EXTENSIONS = {1: "transfer fee", 3: "mint close authority", 4: "confidential transfers", 6: "default account state",
              9: "non-transferable", 10: "interest bearing", 12: "permanent delegate", 14: "transfer hook",
              18: "metadata pointer", 19: "token metadata", 20: "group pointer", 22: "group member pointer",
              25: "scaled UI amount", 26: "pausable"}
SOURCES_NOTE = "chain (mint, metadata, largest holders), DexScreener pairs, Jupiter tokens/v2"


def now_ms() -> int:
    return int(time.time() * 1000)


def cache_path() -> Path:
    from ..data import WRITE_ROOT
    return WRITE_ROOT / "onchain" / "meme" / "safety.json"


def block_paths() -> list[Path]:
    from ..pumpfun_rt import trends
    return trends.block_paths()


def exception_paths() -> list[Path]:
    from ..data import ROOT
    return [Path("/etc/pythia/meme-exceptions.txt"), ROOT / "onchain" / "meme-exceptions.txt"]


def read_lines(paths) -> set[str]:
    out = set()
    for p in paths:
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                v = line.split("#", 1)[0].strip()
                if v:
                    out.add(v)
        except OSError:
            pass
    return out


def read_blocked(paths=None) -> tuple[set[str], set[str]]:
    """(blocked mints, blocked creators) from the owner's block list; "creator:<address>" names a creator."""
    mints, creators = set(), set()
    for v in read_lines(block_paths() if paths is None else paths):
        if v.lower().startswith("creator:"):
            c = v.split(":", 1)[1].strip()
            if c:
                creators.add(c)
        else:
            mints.add(v)
    return mints, creators


# ---------------------------------------------------------------- what the chain holds

@dataclass(frozen=True)
class MintInfo:
    program: str
    mint_authority: str | None
    freeze_authority: str | None
    supply: int
    decimals: int
    initialized: bool
    extensions: tuple = ()


def parse_mint(owner: str, data: bytes) -> MintInfo | None:
    """An SPL mint (classic: 82 bytes; Token-2022: the same 82, padding to 165, the account type 1, then its
    extensions as type u16, length u16, value). None for anything that is not a mint."""
    if owner not in (X.TOKEN, X.TOKEN_2022) or len(data) < 82:
        return None
    if owner == X.TOKEN and len(data) != 82:
        return None
    ma = b58(data[4:36]) if data[0:4] == b"\x01\x00\x00\x00" else None
    fa = b58(data[50:82]) if data[46:50] == b"\x01\x00\x00\x00" else None
    exts = []
    if owner == X.TOKEN_2022 and len(data) > 166 and data[165] == 1:
        pos = 166
        while pos + 4 <= len(data):
            t, n = struct.unpack_from("<HH", data, pos)
            if t == 0:
                break
            exts.append(t)
            pos += 4 + n
    return MintInfo(owner, ma, fa, struct.unpack_from("<Q", data, 36)[0], data[44], data[45] == 1, tuple(exts))


def metadata_address(mint: str) -> str:
    return X.pda([b"metadata", X.key(METADATA_PROGRAM), X.key(mint)], METADATA_PROGRAM)


def parse_metadata(data: bytes) -> dict | None:
    """The parts of a Metaplex metadata account we read: update authority, name, symbol, creators, mutable."""
    try:
        if not data or data[0] != 4:
            return None
        out = {"update_authority": b58(data[1:33]), "mint": b58(data[33:65])}
        pos = 65
        for k in ("name", "symbol", "uri"):
            n = struct.unpack_from("<I", data, pos)[0]
            out[k] = data[pos + 4:pos + 4 + n].rstrip(b"\x00").decode("utf-8", "replace").strip()
            pos += 4 + n
        pos += 2                                         # seller fee
        creators = []
        if data[pos] == 1:
            n = struct.unpack_from("<I", data, pos + 1)[0]
            pos += 5
            for _ in range(min(n, 5)):
                creators.append({"address": b58(data[pos:pos + 32]), "verified": data[pos + 32] == 1})
                pos += 34
        else:
            pos += 1
        out["creators"] = creators
        out["mutable"] = data[pos + 1] == 1 if len(data) > pos + 1 else None
        return out
    except (IndexError, struct.error):
        return None


def holder_share(supply: int, largest: list[tuple[str, int]], owners: dict[str, str | None],
                 pools: set[str]) -> tuple[float | None, dict]:
    """The top 10 holders' share of the supply outside the burn addresses, pools and program vaults left out.
    `largest` (token account, raw amount) as getTokenLargestAccounts gives it, `owners` each account's owner."""
    if not largest:
        return None, {"why": "no holder read"}
    burned, kept, left = 0, [], []
    for acc, amt in largest:
        o = owners.get(acc)
        if o is None:
            return None, {"why": "a large holder's account could not be read"}
        if o in BURN:
            burned += amt
        elif acc in pools or o in pools or not X.on_curve(X.key(o)):
            left.append(acc)
        else:
            kept.append(amt)
    base = supply - burned
    if base <= 0:
        return None, {"why": "no supply outside the burn addresses"}
    top = sorted(kept, reverse=True)[:10]
    return sum(top) / base, {"burned_raw": burned, "pools_left_out": len(left), "holders_counted": len(top)}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _ms(v) -> int | None:
    """A time as ms since the epoch from a number (ms or s) or an ISO string."""
    x = _f(v)
    if x is not None:
        return int(x if x > 1e11 else x * 1000)
    if isinstance(v, str) and v:
        try:
            return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def best_pool(pairs: list[dict], mint: str) -> tuple[dict | None, int | None]:
    """The deepest pool of `mint` on our venues (as base or quote token) and the oldest one's creation time."""
    mine = [p for p in pairs or [] if isinstance(p, dict) and (p.get("chainId") in (None, "solana"))
            and mint in ((p.get("baseToken") or {}).get("address"), (p.get("quoteToken") or {}).get("address"))
            and str(p.get("dexId") or "").lower().startswith(DEXES)]
    if not mine:
        return None, None
    best = max(mine, key=lambda p: _f((p.get("liquidity") or {}).get("usd")) or 0.0)
    born = [t for t in (_ms(p.get("pairCreatedAt")) for p in mine) if t]
    return best, min(born) if born else None


def jup_facts(tok: dict | None) -> dict:
    if not isinstance(tok, dict):
        return {}
    tags = [str(t) for t in tok.get("tags") or []]
    audit = tok.get("audit") or {}
    first = tok.get("firstPool") or {}
    return {"verified": bool(tok.get("isVerified")) or "verified" in tags, "strict": "strict" in tags,
            "tags": tags, "organic_score": _f(tok.get("organicScore")), "organic_label": tok.get("organicScoreLabel"),
            "liquidity_usd": _f(tok.get("liquidity")), "holders": tok.get("holderCount"),
            "top_holders_pct": _f(audit.get("topHoldersPercentage")), "dev": tok.get("dev"),
            "first_pool_ms": _ms(first.get("createdAt")), "launchpad": tok.get("launchpad"),
            "symbol": tok.get("symbol"), "name": tok.get("name")}


# ---------------------------------------------------------------- the verdict

@dataclass
class Verdict:
    mint: str
    ok: bool
    reasons: list[str]
    t: int
    facts: dict = field(default_factory=dict)

    def record(self) -> dict:
        return asdict(self)


def judge(mint: str, mint_acc, meta: bytes | None, largest: list[tuple[str, int]] | None,
          owners: dict[str, str | None] | None, pairs: list[dict] | None, jup: dict | None,
          blocked: tuple[set, set], exceptions: set, now: int) -> Verdict:
    """The verdict from what was read. `mint_acc` a guard.Account (or None: not there); `largest` None when the
    read failed; `pairs` DexScreener's pairs; `jup` Jupiter's token entry."""
    why: list[str] = []
    facts: dict = {"sources": SOURCES_NOTE}
    jf = jup_facts(jup)
    facts["jupiter"] = jf
    md = parse_metadata(meta) if meta else None
    facts["metadata"] = md
    b_mints, b_creators = blocked
    if mint in b_mints:
        why.append("the mint is on the owner's block list")
    creators = {c for c in [jf.get("dev"), (md or {}).get("update_authority")]
                + [c["address"] for c in (md or {}).get("creators") or []] if c}
    hit = sorted(creators & b_creators)
    if hit:
        why.append(f"its creator {hit[0][:8]} is on the owner's block list")
    if mint == WSOL:
        why.append("wrapped SOL is not a memecoin")
    mi = parse_mint(mint_acc.owner, mint_acc.data) if mint_acc is not None else None
    if mint_acc is None:
        why.append("the mint account does not exist")
    elif mi is None:
        why.append("the account is not an SPL mint")
    else:
        facts.update(program="token" if mi.program == X.TOKEN else "token-2022", decimals=mi.decimals,
                     supply=mi.supply, mint_authority=mi.mint_authority, freeze_authority=mi.freeze_authority)
        if mi.program == X.TOKEN_2022:
            named = [EXTENSIONS.get(e, f"extension {e}") for e in mi.extensions]
            why.append("a Token-2022 mint (refused, as the guard does)" + (f": {', '.join(named)}" if named else ""))
        if not mi.initialized:
            why.append("the mint is not initialised")
        exempt = mint in exceptions
        if mi.mint_authority and not exempt:
            why.append("it still has a mint authority (more can be minted at any time)")
        if mi.freeze_authority and not exempt:
            why.append("it has a freeze authority (our token account could be frozen)")
        if exempt and (mi.mint_authority or mi.freeze_authority):
            facts["exception"] = "on the owner's exception list: mint and freeze authority allowed"
    pool, born = best_pool(pairs or [], mint)
    liq = _f(((pool or {}).get("liquidity") or {}).get("usd"))
    facts["pool"] = {"dex": (pool or {}).get("dexId"), "address": (pool or {}).get("pairAddress"),
                     "liquidity_usd": liq, "created_ms": born, "price_usd": _f((pool or {}).get("priceUsd"))}
    if pool is None:
        why.append("no pool on Raydium, Meteora, Orca or PumpSwap")
    elif liq is None or liq < MIN_LIQUIDITY_USD:
        why.append(f"its best pool holds {liq or 0:,.0f} USD (at least {MIN_LIQUIDITY_USD:,.0f})")
    born = born or jf.get("first_pool_ms")
    if born is None:
        why.append("the age of its first pool is not known")
    elif now - born < MIN_AGE_MS:
        why.append(f"its first pool is {(now - born) / 60_000:.0f} min old (at least {MIN_AGE_MS // 60_000} min)")
    share = None
    if mi is not None and largest is not None and owners is not None:
        pools = {p.get("pairAddress") for p in pairs or [] if isinstance(p, dict) and p.get("pairAddress")}
        share, hf = holder_share(mi.supply, largest, owners, pools)
        facts["holders"] = hf
    if share is None and jf.get("top_holders_pct") is not None:
        share = jf["top_holders_pct"] / 100
        facts["holders_from"] = "jupiter audit"
    facts["top10_share"] = share
    if share is None:
        why.append("the largest holders could not be read")
    elif share >= MAX_TOP10_SHARE:
        why.append(f"the top 10 holders hold {share:.0%} (must be under {MAX_TOP10_SHARE:.0%}; pools and burns left out)")
    return Verdict(mint, not why, why, now, facts)


# ---------------------------------------------------------------- reading it

class Sources:
    """The reads behind a verdict. `rpc` has .call(method, params) (pumpfun_rt.live_exec.Rpc), `jup` a
    jupiter.Jupiter for tokens/v2, `dex(url)` returns DexScreener's JSON. Each read that fails leaves its
    part unknown, which refuses the coin with its reason."""

    def __init__(self, rpc, jup=None, dex=None):
        self.rpc, self.jup, self.dex = rpc, jup, dex
        self.pairs_cache: dict[str, list] = {}

    def accounts(self, keys: list[str]) -> dict:
        from . import guard as G
        res = self.rpc.call("getMultipleAccounts", [keys, {"encoding": "base64", "commitment": "confirmed"}]) or {}
        return {k: G.account_of(v) for k, v in zip(keys, res.get("value") or [])}

    def largest(self, mint: str) -> list[tuple[str, int]] | None:
        try:
            res = self.rpc.call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}]) or {}
            return [(r["address"], int(r["amount"])) for r in res.get("value") or []]
        except Exception:
            return None

    def owners(self, accounts: list[str]) -> dict[str, str | None]:
        from . import guard as G
        out: dict[str, str | None] = {}
        got = self.accounts(accounts) if accounts else {}
        for k in accounts:
            a = got.get(k)
            t = G.parse_token(a.data[:165]) if a is not None and a.owner in (X.TOKEN, X.TOKEN_2022) \
                and len(a.data) >= 165 else None
            out[k] = t.owner if t is not None else None
        return out

    def pairs(self, mints: list[str]) -> dict[str, list]:
        """DexScreener's pairs per mint, 30 at a time; a failed read leaves the mints out (refused: no pool)."""
        want = [m for m in dict.fromkeys(mints) if m not in self.pairs_cache]
        for i in range(0, len(want), 30):
            part = want[i:i + 30]
            try:
                got = self.dex(DEX_URL + urllib.parse.quote(",".join(part), safe=",")) if self.dex else None
            except Exception:
                got = None
            if not isinstance(got, list):
                continue
            for m in part:
                self.pairs_cache[m] = [p for p in got if isinstance(p, dict) and m in (
                    (p.get("baseToken") or {}).get("address"), (p.get("quoteToken") or {}).get("address"))]
        return {m: self.pairs_cache.get(m) for m in mints}

    def jup_token(self, mint: str) -> dict | None:
        if self.jup is None:
            return None
        try:
            got = self.jup.get("/tokens/v2/search", {"query": mint})
        except Exception:
            return None
        return next((t for t in got or [] if isinstance(t, dict) and t.get("id") == mint), None)


def check(mint: str, src: Sources, blocked: tuple[set, set] | None = None, exceptions: set | None = None,
          now: int | None = None, cache: bool = True) -> Verdict:
    """Read everything for one mint and judge it; the verdict goes into the cache. Never raises on a bad read."""
    now = now_ms() if now is None else now
    blocked = read_blocked() if blocked is None else blocked
    exceptions = read_lines(exception_paths()) if exceptions is None else exceptions
    meta_key = metadata_address(mint)
    try:
        acc = src.accounts([mint, meta_key])
        mint_acc, meta = acc.get(mint), (acc.get(meta_key).data if acc.get(meta_key) is not None else None)
        read_ok = True
    except Exception as e:
        mint_acc, meta, read_ok = None, None, False
        err = f"{type(e).__name__}"
    largest = src.largest(mint) if read_ok else None
    owners = None
    if largest is not None:
        try:
            owners = src.owners([a for a, _ in largest])
        except Exception:
            owners = None
    pairs = src.pairs([mint]).get(mint)
    v = judge(mint, mint_acc, meta, largest, owners, pairs, src.jup_token(mint), blocked, exceptions, now)
    if not read_ok:
        v.reasons.insert(0, f"the mint could not be read from the chain ({err})")
        v.ok = False
    if pairs is None:
        v.reasons.append("DexScreener's pairs could not be read")
        v.ok = False
    if cache:
        save(v)
    return v


def load_cache(path: Path | None = None) -> dict:
    try:
        d = json.loads((path or cache_path()).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(v: Verdict, path: Path | None = None, keep_ms: int = 7 * 86_400_000) -> None:
    p = path or cache_path()
    d = {k: r for k, r in load_cache(p).items() if isinstance(r, dict) and v.t - int(r.get("t") or 0) < keep_ms}
    d[v.mint] = v.record()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, default=str), encoding="utf-8")
    tmp.replace(p)


def cached(mint: str, max_age_ms: int, now: int | None = None, path: Path | None = None) -> dict | None:
    """The cached verdict of `mint` when it is at most max_age_ms old."""
    now = now_ms() if now is None else now
    r = load_cache(path).get(mint)
    if isinstance(r, dict) and 0 <= now - int(r.get("t") or 0) <= max_age_ms:
        return r
    return None


def default_sources(env=None) -> Sources:
    from ..ops import trending as TR
    from ..pumpfun_rt import live_exec as PX
    from . import live_gate as LG
    from .jupiter import Jupiter
    env = os.environ if env is None else env
    return Sources(PX.Rpc(env.get(LG.ENV_RPC) or LG.DEFAULT_RPC), Jupiter(), TR.http_json)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the meme module's per-coin safety check (read only)")
    ap.add_argument("mints", nargs="+")
    a = ap.parse_args(argv)
    src = default_sources()
    bad = 0
    for m in a.mints:
        v = check(m, src)
        bad += not v.ok
        print(f"{m}: " + ("passes" if v.ok else "REFUSED: " + "; ".join(v.reasons)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
