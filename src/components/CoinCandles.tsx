// The live chart of a coin the pump.fun bot holds or just sold: candles from every trade on it
// as the live service streams them (GET /api/pumpfun/live/ws), with what the bot paid, its take
// profit and stop lines, the buy, the sale and the time stop. Drawn here; nothing is fetched.

import { useMemo } from "react";
import { ExternalLink } from "lucide-react";
import { Badge } from "../design";
import {
  candles,
  coinBadge,
  coinReturn,
  dexscreener,
  eur,
  exitWords,
  short,
  sol,
  solscanToken,
  timeStopLeft,
  type FeedCoin,
  type SolEur,
} from "../pumpfunLive";

const W = 600;
const H = 220;
const PAD = { l: 6, r: 64, t: 10, b: 22 };
/** Candle width in time: a 5 minute hold makes about 60 of them. */
export const BUCKET_MS = 5_000;
/** How much of the time before the buy the chart shows, when there is any. */
const LEAD_MS = 30_000;

function pctText(r: number | null): string {
  return r == null ? "n/a" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(1)} %`;
}

function clock(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function CoinCandles({ coin, nowMs, rate }: { coin: FeedCoin; nowMs: number; rate: SolEur | null }) {
  const endMs = coin.exit?.ms ?? nowMs;
  const fromMs = coin.land_ms != null ? coin.land_ms - LEAD_MS : coin.points[0]?.[0] ?? nowMs;
  const deadline = coin.land_ms != null && coin.time_s != null ? coin.land_ms + coin.time_s * 1000 : null;
  const toMs = Math.max(endMs, deadline != null && !coin.exit ? deadline : endMs) + BUCKET_MS;
  const bars = useMemo(
    () => candles(coin.points.filter((p) => p[0] >= fromMs), BUCKET_MS, endMs),
    [coin.points, fromMs, endMs],
  );
  const ret = coinReturn(coin);
  const left = timeStopLeft(coin, nowMs);
  const entry = coin.entry_price;
  const tpPx = entry != null && coin.tp != null ? entry * (1 + coin.tp) : null;
  const slPx = entry != null && coin.sl != null ? entry * (1 - coin.sl) : null;

  const lo = Math.min(...bars.map((b) => b.low), ...[entry, slPx, coin.exit?.price].filter((v): v is number => v != null && v > 0));
  const hi = Math.max(...bars.map((b) => b.high), ...[entry, tpPx, coin.exit?.price].filter((v): v is number => v != null && v > 0));
  const ok = Number.isFinite(lo) && Number.isFinite(hi) && hi > 0;
  const span = ok ? Math.max(hi - lo, hi * 0.02) : 1;
  const yLo = ok ? lo - span * 0.06 : 0;
  const yHi = ok ? hi + span * 0.06 : 1;
  const x = (t: number) => PAD.l + ((t - fromMs) / Math.max(toMs - fromMs, 1)) * (W - PAD.l - PAD.r);
  const y = (p: number) => PAD.t + (1 - (p - yLo) / (yHi - yLo)) * (H - PAD.t - PAD.b);
  const bw = Math.max(1.5, (x(fromMs + BUCKET_MS) - x(fromMs)) * 0.7);

  const level = (p: number | null, color: string, text: string, dash?: string) =>
    p == null ? null : (
      <g key={text}>
        <line x1={PAD.l} x2={W - PAD.r} y1={y(p)} y2={y(p)} stroke={color} strokeWidth={1} strokeDasharray={dash} opacity={0.8} />
        <text x={W - PAD.r + 4} y={y(p) + 4} fontSize={11} fill={color}>
          {text}
        </text>
      </g>
    );
  const mark = (t: number | null, color: string, text: string, dash?: string) =>
    t == null || t < fromMs ? null : (
      <g key={text}>
        <line x1={x(t)} x2={x(t)} y1={PAD.t} y2={H - PAD.b} stroke={color} strokeWidth={1} strokeDasharray={dash} opacity={0.7} />
        <text x={Math.min(x(t) + 3, W - PAD.r - 40)} y={H - 6} fontSize={11} fill={color}>
          {text}
        </text>
      </g>
    );

  const title = coin.symbol || coin.name || short(coin.mint);
  const open = !coin.exit;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-semibold text-ink">{title}</span>
        <Badge tone={open ? "accent" : "neutral"}>{coinBadge(coin)}</Badge>
        <span className={`text-[15px] font-semibold tabular-nums ${ret == null ? "text-muted" : ret >= 0 ? "text-up" : "text-down"}`}>{pctText(ret)}</span>
        {left != null && <span className="text-[13px] tabular-nums text-muted">time stop in {clock(left)}</span>}
        {coin.exit && <span className="text-[13px] text-muted">{exitWords(coin.exit.why)}{coin.exit.pnl_sol != null ? `, ${sol(coin.exit.pnl_sol, true)}` : ""}</span>}
        <span className="ml-auto flex gap-3 text-[13px]">
          <a className="inline-flex items-center gap-1 text-accent hover:underline" href={dexscreener(coin.mint)} target="_blank" rel="noreferrer noopener">
            DexScreener <ExternalLink size={12} aria-hidden />
          </a>
          <a className="inline-flex items-center gap-1 text-accent hover:underline" href={solscanToken(coin.mint)} target="_blank" rel="noreferrer noopener">
            Solscan <ExternalLink size={12} aria-hidden />
          </a>
        </span>
      </div>
      {bars.length === 0 || !ok ? (
        <div style={{ height: H }} className="flex items-center justify-center rounded-2xl bg-surface-2 px-4 text-center text-[13px] text-muted">
          Waiting for the first trade on this coin.
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full rounded-2xl bg-surface-2"
          role="img"
          aria-label={`${title}: ${bars.length} candles of 5 seconds, ${pctText(ret)} against the price paid`}
        >
          {level(tpPx, "var(--color-up)", `+${Math.round((coin.tp ?? 0) * 100)} %`, "4 3")}
          {level(entry, "var(--color-muted)", "paid")}
          {level(slPx, "var(--color-down)", `-${Math.round((coin.sl ?? 0) * 100)} %`, "4 3")}
          {mark(coin.land_ms, "var(--color-accent)", "buy")}
          {mark(coin.exit?.ms ?? null, "var(--color-text)", coin.state === "skipped" ? "not bought" : "sold")}
          {open && mark(deadline, "var(--color-muted)", "time stop", "2 3")}
          {bars.map((b) => {
            const up = b.close >= b.open;
            const color = up ? "var(--color-up)" : "var(--color-down)";
            const cx = x(b.t + BUCKET_MS / 2);
            const top = y(Math.max(b.open, b.close));
            const bot = y(Math.min(b.open, b.close));
            return (
              <g key={b.t}>
                <line x1={cx} x2={cx} y1={y(b.high)} y2={y(b.low)} stroke={color} strokeWidth={1} />
                <rect x={cx - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} fill={color} rx={1} />
              </g>
            );
          })}
        </svg>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
        <span>paid {sol(coin.cost_sol)}{eur(coin.cost_sol, rate) ? ` (${eur(coin.cost_sol, rate)})` : ""}</span>
        {open && coin.mark_sol != null && <span>worth {sol(coin.mark_sol)}{eur(coin.mark_sol, rate) ? ` (${eur(coin.mark_sol, rate)})` : ""}</span>}
        <span>{coin.points.length} trades seen</span>
        <span>{coin.venue === "pool" ? "PumpSwap pool" : "bonding curve"}</span>
      </div>
    </div>
  );
}
