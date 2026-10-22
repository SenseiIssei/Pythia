// The pump.fun wallet: the owner's real-money test of the pump.fun bot, run by
// the live service on the server (docs/PUMPFUN-LIVE.md). The page shows where to
// send SOL (address and QR code, made here in the browser), what the wallet
// holds, what the bot does and measured, and two controls that can only make
// it safer: lower limits and the kill switch. There is no withdraw or transfer:
// the owner withdraws with his own wallet and his backup.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, OctagonX, QrCode, RefreshCw, Save } from "lucide-react";
import { AreaChart, Badge, Button, Field, List, ListRow, Notice, Page, inputCls } from "../design";
import { ConfirmAction, KeyStats, LoadingRows, More, Nothing, Row, Section, plural } from "../pagekit";
import { encodeQr, qrPath } from "../qr";
import {
  LIMIT_LABEL,
  canControl,
  ceilings,
  eur,
  exitWords,
  holdWords,
  limitInput,
  parseLimits,
  pumpfunKill,
  pumpfunLive,
  savePumpfunLimits,
  short,
  sol,
  solEurChange,
  solscanToken,
  stateLine,
  tone,
  tradeStats,
  type LimitInput,
  type LimitKey,
  type PumpfunTrade,
  type PumpfunView,
  type SolEur,
} from "../pumpfunLive";

const REFRESH_MS = 15_000;

function AddressQr({ address }: { address: string }) {
  const { d, n } = useMemo(() => {
    const code = encodeQr(address, "M");
    return { d: qrPath(code), n: code.size + 8 };
  }, [address]);
  // Dark modules on a light tile in both themes: scanners do not read an inverted code.
  return (
    <div className="mx-auto w-full max-w-[240px] rounded-2xl bg-white p-2">
      <svg viewBox={`0 0 ${n} ${n}`} role="img" aria-label={`QR code of the wallet address ${address}`} className="block h-auto w-full" shapeRendering="crispEdges">
        <path d={d} className="fill-black" />
      </svg>
    </div>
  );
}

function CopyAddress({ address }: { address: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="secondary"
      size="sm"
      icon={done ? Check : Copy}
      onClick={() => {
        void navigator.clipboard?.writeText(address).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 2000);
        });
      }}
    >
      {done ? "Copied" : "Copy address"}
    </Button>
  );
}

function Limits({ v, onSaved }: { v: PumpfunView; onSaved: () => void }) {
  const s = v.status;
  const c = ceilings(s?.ack, v.hard);
  const [input, setInput] = useState<LimitInput>(() => limitInput(v.settings));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const { patch, errors } = parseLimits(input, c);
  const control = canControl();
  const keys: LimitKey[] = ["maxTotalSol", "maxDailyLossSol", "maxTradeSol", "maxOpen"];
  const ackOf: Record<LimitKey, number | null | undefined> = {
    maxTotalSol: s?.ack.maxTotalSol,
    maxDailyLossSol: s?.ack.maxDailyLossSol,
    maxTradeSol: s?.ack.maxTradeSol,
    maxOpen: null,
  };
  const inForce: Record<LimitKey, number | null | undefined> = {
    maxTotalSol: s?.limits?.maxTotalSol,
    maxDailyLossSol: s?.limits?.maxDailyLossSol,
    maxTradeSol: s?.limits?.maxTradeSol,
    maxOpen: s?.limits?.maxOpen,
  };
  const fmt = (k: LimitKey, x: number | null | undefined) => (x == null ? "n/a" : k === "maxOpen" ? String(x) : sol(x, false, 3));
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await savePumpfunLimits(patch);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 3000);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section
      title="Limits"
      hint="The confirmation file on the server sets the most the bot may risk; the code caps it again (test: 2 SOL in all, 0.5 SOL a day, 0.1 SOL a trade). Here you can only set lower limits. Raising one needs a new confirmation file on the server."
    >
      <div className="divide-y divide-line">
        {keys.map((k) => (
          <Row
            key={k}
            label={LIMIT_LABEL[k]}
            value={fmt(k, inForce[k])}
            valueSub="in force"
            sub={
              <>
                {k !== "maxOpen" && <>file {fmt(k, ackOf[k])} · </>}
                at most {fmt(k, k === "maxOpen" ? v.hard.maxOpen : c?.[k] ?? null)}
                {v.settings[k] != null && <> · yours {fmt(k, v.settings[k])}</>}
              </>
            }
          />
        ))}
      </div>
      {control ? (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {keys.map((k) => (
              <Field key={k} label={`${LIMIT_LABEL[k]}${k === "maxOpen" ? "" : " (SOL)"}`} hint="Empty: the file's value" error={errors[k]}>
                <input
                  className={inputCls}
                  inputMode="decimal"
                  value={input[k]}
                  placeholder={fmt(k, k === "maxOpen" ? c?.maxOpen ?? null : c?.[k] ?? null)}
                  onChange={(e) => setInput({ ...input, [k]: e.target.value })}
                  aria-label={LIMIT_LABEL[k]}
                />
              </Field>
            ))}
          </div>
          {err && <Notice tone="danger">{err}</Notice>}
          <Button icon={saved ? Check : Save} variant="secondary" disabled={busy || Object.keys(errors).length > 0 || !c} onClick={() => void save()}>
            {saved ? "Saved" : "Save lower limits"}
          </Button>
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">Limits are set through the connected backend on the server; the desktop app only shows them.</p>
      )}
    </Section>
  );
}

const pctText = (r: number | null | undefined) => (r == null || !Number.isFinite(r) ? "n/a" : `${r > 0 ? "+" : ""}${(r * 100).toFixed(1)} %`);
const tradeName = (t: PumpfunTrade) => t.symbol || t.name || short(t.mint);

/** How the bot did over the closed trades the service keeps: the running P&L and what it adds up to. */
function Performance({ trades, rate }: { trades: PumpfunTrade[]; rate: SolEur | null }) {
  const s = useMemo(() => tradeStats(trades), [trades]);
  const [at, setAt] = useState<number | null>(null);
  const oldest = useMemo(() => [...trades].sort((a, b) => (a.exitMs ?? 0) - (b.exitMs ?? 0)), [trades]);
  const shown = at == null ? s.pnlSol : s.curve[at];
  return (
    <Section title="Performance" hint="Every closed trade added up in order, fees included. The line is the running profit or loss in SOL; euro at today's SOL price.">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div className={`tabular text-2xl font-semibold ${tone(shown) === "up" ? "text-up" : tone(shown) === "down" ? "text-down" : "text-ink"}`}>{sol(shown, true)}
          {rate && <span className="ml-2 text-base font-medium">{eur(shown, rate, true)}</span>}
        </div>
        <div className="text-[13px] text-muted">{at == null || at === 0 ? `${plural(s.n, "trade")}` : `after trade ${at}: ${tradeName(oldest[at - 1])}`}</div>
      </div>
      <AreaChart
        data={s.curve}
        height={170}
        baseline={0}
        label={`Running profit or loss over ${s.n} trades, now ${sol(s.pnlSol, true)}`}
        onScrub={(x) => setAt(x ? x.index : null)}
        empty="The line starts with the first closed trade."
      />
      {s.n > 0 && (
        <div className="mt-3 divide-y divide-line">
          <Row label="Trades" value={String(s.n)} valueSub={`${s.wins} won, ${s.n - s.wins} lost`} help="Closed trades the live service keeps for the app (its newest ones)." />
          <Row label="Won" value={s.winRate == null ? "n/a" : `${Math.round(s.winRate * 100)} %`} help="Share of trades that ended with more SOL than they cost." />
          <Row label="Average per trade" value={pctText(s.avgRet)} tone={tone(s.avgRet)} help="The mean return of a trade on its stake, after fees." />
          <Row label="Staked, got back" value={sol(s.proceedsSol, false, 4)} valueSub={`of ${sol(s.stakeSol, false, 4)}${rate ? ` (${eur(s.proceedsSol, rate)} of ${eur(s.stakeSol, rate)})` : ""}`} help="SOL put into these trades and SOL that came back out of them." />
          {s.best && <Row label="Best trade" value={sol(s.best.pnlSol, true)} valueSub={eur(s.best.pnlSol, rate, true) || undefined} tone="up" sub={`${tradeName(s.best)} · ${pctText(s.best.ret)}`} />}
          {s.worst && <Row label="Worst trade" value={sol(s.worst.pnlSol, true)} valueSub={eur(s.worst.pnlSol, rate, true) || undefined} tone="down" sub={`${tradeName(s.worst)} · ${pctText(s.worst.ret)}`} />}
          <Row label="Average holding time" value={holdWords(s.avgHoldS)} help="From the buy landing to the sale." />
        </div>
      )}
    </Section>
  );
}

type TradeFilter = "all" | "won" | "lost";

/** Every closed trade the service keeps, newest first, with what it cost, what came back and a link to the token. */
function TradeList({ trades, rate }: { trades: PumpfunTrade[]; rate: SolEur | null }) {
  const [filter, setFilter] = useState<TradeFilter>("all");
  const rows = trades.filter((t) => filter === "all" || (filter === "won" ? (t.pnlSol ?? 0) > 0 : (t.pnlSol ?? 0) <= 0));
  return (
    <Section title="Live trades" hint="Every closed trade of the bot, newest first. Each one also went to Telegram.">
      {trades.length > 0 ? (
        <>
          <div className="mb-3 flex gap-2" role="group" aria-label="Show trades">
            {(["all", "won", "lost"] as TradeFilter[]).map((f) => (
              <Button key={f} size="sm" variant={filter === f ? "primary" : "secondary"} onClick={() => setFilter(f)} aria-pressed={filter === f}>
                {f === "all" ? `All ${trades.length}` : f === "won" ? "Won" : "Lost"}
              </Button>
            ))}
          </div>
          <List>
            {rows.map((t, i) => (
              <ListRow
                key={`${t.exitMs}-${t.mint}-${i}`}
                title={
                  <span className="flex items-center gap-2">
                    {tradeName(t)}
                    {t.mode === "test" && <Badge tone="warn">test</Badge>}
                    {t.mint && (
                      <a href={solscanToken(t.mint)} target="_blank" rel="noreferrer noopener" className="fl-focus text-muted hover:text-ink" aria-label={`${tradeName(t)} on Solscan`}>
                        <ExternalLink size={14} />
                      </a>
                    )}
                  </span>
                }
                subtitle={[
                  t.exitMs ? new Date(t.exitMs).toLocaleString() : null,
                  `${sol(t.stakeSol, false, 4)} in, ${sol(t.proceedsSol, false, 4)} out`,
                  `held ${holdWords(t.holdS)}`,
                  exitWords(t.exitWhy) || null,
                  t.rule,
                  t.latBuyMs != null ? `landed ${Math.round(t.latBuyMs)} ms` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
                right={<span className={tone(t.pnlSol) === "up" ? "text-up" : tone(t.pnlSol) === "down" ? "text-down" : "text-ink"}>{sol(t.pnlSol, true)}</span>}
                rightSub={[eur(t.pnlSol, rate, true), t.ret == null ? "" : pctText(t.ret)].filter(Boolean).join(" · ") || undefined}
              />
            ))}
          </List>
          {rows.length === 0 && <p className="text-sm text-muted">No {filter} trade yet.</p>}
        </>
      ) : (
        <p className="text-sm text-muted">No live trade yet.</p>
      )}
    </Section>
  );
}

export function PumpfunWallet() {
  const [v, setV] = useState<PumpfunView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [killMsg, setKillMsg] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setV(await pumpfunLive());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const kill = async () => {
    try {
      const k = await pumpfunKill();
      setKillMsg(k.already ? "The kill file was already there." : "Kill switch set. The bot buys nothing more and sells what is open.");
      void load();
    } catch (e) {
      setKillMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const s = v?.status ?? null;
  const st = v ? stateLine(v) : null;
  const rate = v?.solEur ?? null;
  return (
    <Page
      title="pump.fun live"
      subtitle="Real money, traded by the live service on the server under the limits you set. Paper results so far are negative; size everything as a total loss."
      right={<Button variant="ghost" size="sm" icon={RefreshCw} onClick={() => void load()}>Refresh</Button>}
    >
      {err && <Notice tone="danger" title="Could not read the live service">{err}</Notice>}
      {!v && !err && <LoadingRows rows={4} label="Reading the live service" />}
      {v && st && (
        <>
          <Notice tone={st.level === "ok" ? "success" : st.level === "bad" ? "danger" : st.level === "warn" ? "warning" : "info"} title={st.label}>
            {st.detail}
            {s && s.gate.length > 1 && (
              <ul className="mt-1 list-disc pl-5">
                {s.gate.slice(1, 8).map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            )}
          </Notice>

          <KeyStats
            items={[
              { label: "Wallet balance", value: sol(s?.balanceSol ?? null), sub: s?.balanceT ? `read ${new Date(s.balanceT).toLocaleTimeString()}` : "not read yet", help: "The SOL in the bot's wallet, read from the chain by the live service." },
              ...(rate
                ? [{ label: "Worth in euro", value: eur(s?.balanceSol ?? null, rate) || "n/a", sub: `1 SOL = ${eur(1, rate)} · ${pctText(solEurChange(rate))} today`, help: "The wallet's SOL at the live SOL/EUR price (Kraken, refreshed every 15 seconds). It moves with SOL even when the bot does nothing." }]
                : []),
              { label: "Today", value: sol(s?.pnlTodaySol ?? 0, true), tone: tone(s?.pnlTodaySol), sub: s ? `${eur(s.pnlTodaySol, rate, true) ? `${eur(s.pnlTodaySol, rate, true)} · ` : ""}${plural(s.tradesToday, "trade")}, ${s.winsToday} won` : undefined, help: "Realised profit or loss of the bot today (UTC), fees included." },
              { label: "Since the first live trade", value: sol(s?.pnlTotalSol ?? 0, true), tone: tone(s?.pnlTotalSol), sub: s ? `${eur(s.pnlTotalSol, rate, true) ? `${eur(s.pnlTotalSol, rate, true)} · ` : ""}${plural(s.tradesTotal, "trade")}` : undefined, help: "Everything the bot has won or lost since its first live trade. The total budget stop counts this." },
            ]}
          />

          <Performance trades={v.trades} rate={rate} />

          <Section title="Fund the wallet" hint="Send SOL from your own wallet or exchange to this address. That is the only way money gets in.">
            {v.address ? (
              <div className="space-y-4">
                <AddressQr address={v.address} />
                <div className="break-all text-center font-code text-[13px] text-ink">{v.address}</div>
                <div className="flex justify-center">
                  <CopyAddress address={v.address} />
                </div>
                <Notice tone="info" title="Pythia never moves money out">
                  There is no withdraw or transfer anywhere in Pythia. To take money out, import your backup secret (shown once when the wallet was made) into your own wallet, for example Phantom, and send it from there.
                </Notice>
              </div>
            ) : (
              <Nothing icon={QrCode} title="No wallet yet">
                The owner makes the wallet on the server with the wallet tool (docs/PUMPFUN-LIVE.md, step 1). Its public address shows up here.
              </Nothing>
            )}
          </Section>

          <Section title="Stop" hint="The kill switch creates a file on the server: the bot buys nothing more and sells what is open. To allow buys again, delete reports/pumpfun_rt/KILL on the server by hand; the app cannot undo it.">
            {v.killFile ? (
              <Notice tone="danger" title="Kill switch is on">Delete reports/pumpfun_rt/KILL in the lab's data folder on the server to allow buys again.</Notice>
            ) : (
              <ConfirmAction
                icon={OctagonX}
                title="Stop the bot"
                confirmLabel="Stop trading now"
                disabled={!canControl()}
                question="This writes the kill file on the server. The bot buys nothing more and sells every open position at once. Only deleting the file on the server allows buys again."
                onConfirm={() => void kill()}
              >
                Stop trading now
              </ConfirmAction>
            )}
            {killMsg && <p className="mt-3 text-sm text-muted">{killMsg}</p>}
          </Section>

          <Limits key={v.settings.updatedMs} v={v} onSaved={() => void load()} />

          <Section title="Open positions" hint="What the bot holds now, from its own book.">
            {s && s.positions.length > 0 ? (
              <List>
                {s.positions.map((p) => (
                  <ListRow
                    key={`${p.pid}-${p.mint}`}
                    title={p.symbol || p.name || short(p.mint)}
                    subtitle={`${p.venue ?? "?"} · ${p.state ?? "?"} · ${short(p.mint)}`}
                    right={sol(p.markSol ?? p.costSol)}
                    rightSub={`${eur(p.markSol ?? p.costSol, rate) ? `${eur(p.markSol ?? p.costSol, rate)} · ` : ""}cost ${sol(p.costSol)}`}
                  />
                ))}
              </List>
            ) : (
              <p className="text-sm text-muted">Nothing open.</p>
            )}
            {s && s.leftovers.length > 0 && <Notice tone="warning" className="mt-3" title="Positions from before a restart">{plural(s.leftovers.length, "position")} being sold by the live service.</Notice>}
            {s && s.holdings.length > 0 && (
              <More title={`Tokens in the wallet on chain (${s.holdings.length})`}>
                <div className="divide-y divide-line">
                  {s.holdings.map((h) => (
                    <Row key={h.mint} label={short(h.mint)} value={h.amount.toLocaleString()} sub="raw token units" />
                  ))}
                </div>
              </More>
            )}
          </Section>

          <Section title="Measured execution" hint="The point of the test: how fast our orders land, what they really pay, against what the paper model assumes.">
            {v.execution && v.execution.fills > 0 ? (
              <>
                <p className="text-sm leading-relaxed text-ink">{v.execution.verdict}</p>
                <div className="mt-2 divide-y divide-line">
                  <Row label="Buy latency, median" value={v.execution.latBuyMs.median == null ? "n/a" : `${Math.round(v.execution.latBuyMs.median)} ms`} sub={`assumed ${v.execution.assumed.latMedianMs ?? "?"} ms`} valueSub={`${v.execution.latBuyMs.n} fills`} />
                  <Row label="Buy slippage, median" value={v.execution.slipBuy.median == null ? "n/a" : `${(v.execution.slipBuy.median * 100).toFixed(1)} %`} sub={v.execution.paperSlip.median == null ? undefined : `paper ${(v.execution.paperSlip.median * 100).toFixed(1)} %`} />
                  <Row label="Network fee, median" value={sol(v.execution.feeSol.median, false, 6)} sub={`assumed ${sol(v.execution.assumed.txFeeSol, false, 6)}`} />
                  <Row label="Failed orders" value={String(v.execution.failed)} />
                </div>
              </>
            ) : (
              <p className="text-sm text-muted">No live fill yet.</p>
            )}
          </Section>

          <TradeList trades={v.trades} rate={rate} />

          <More title="How this works">
            <div className="space-y-2 text-sm leading-relaxed text-muted">
              <p>Funding: you send SOL from your own wallet or exchange to the address above. Pythia never sends money anywhere; it only buys and sells pump.fun tokens with the wallet's SOL, within the limits.</p>
              <p>Withdrawing: import the backup secret into your own wallet (Phantom: Add wallet, Import private key) and send the SOL wherever you like.</p>
              <p>Every fill and failure goes to Telegram at once, and a daily card shows the balance, the P&amp;L and the measured latency. Stops: the daily loss limit and the total budget end buying by themselves.</p>
              <p>pump.fun's terms forbid bots on its website and API. The bot uses neither: it reads the public chain and sends plain buy and sell transactions to a public RPC. Taxes on any gains are your matter.</p>
              {s?.simulate?.t != null && <p>Last dry run (simulation, nothing sent): {new Date(s.simulate.t).toLocaleString()}, {s.simulate.ok ? "ok" : "failed"}.</p>}
            </div>
          </More>
        </>
      )}
    </Page>
  );
}
