import { useState } from "react";
import { Play, Pause, Radio, FlaskConical, AlertTriangle, ShieldCheck, Lock, RefreshCw } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, Sparkline, fmtUsd } from "../components/ui";
import { PnlLines } from "../components/PnlBreakdown";
import { researchAvailable, runValidation } from "../research";
import type { Gate, GateUnit, Passport, StrategyConfig } from "../types";

export function Strategies() {
  const { strategies, passports } = useStore();
  return (
    <div className="animate-fade-in">
      <PageHeader title="Strategies" subtitle="Prove in paper · earn the passport · then arm live deliberately" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {strategies
          .filter((s) => s.id !== "manual")
          .map((s) => (
            <StrategyCard key={s.id} s={s} passport={passports.get(s.id)} />
          ))}
      </div>
    </div>
  );
}

function StrategyCard({ s, passport }: { s: StrategyConfig; passport?: Passport }) {
  const { setStrategyState, setStrategyParam } = useStore();
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  const [armErr, setArmErr] = useState("");

  const live = s.state === "live";
  const paused = s.state === "paused";
  const ready = passport?.liveReady ?? false;

  async function armLive() {
    if (typed.trim() !== s.name) return;
    setArmErr("");
    try {
      await setStrategyState(s.id, "live");
      setConfirm(false);
      setTyped("");
    } catch (e) {
      // The engine is the authority: if it refuses, say why.
      setArmErr(String(e instanceof Error ? e.message : e));
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold">{s.name}</span>
            <Badge tone={live ? "red" : paused ? "neutral" : "cyan"}>
              {live ? "LIVE" : paused ? "PAUSED" : "PAPER"}
            </Badge>
          </div>
          <div className="mt-0.5 text-xs text-cyber-text-faint">
            {s.kind} · {s.universe.length} markets · budget {s.budgetPct}%
          </div>
        </div>
        <div className={`text-right text-lg font-bold ${s.pnl >= 0 ? "text-success" : "text-danger"}`}>
          {fmtUsd(s.pnl)}
          <div className="text-xs font-normal text-cyber-text-faint">
            {s.trades} trades · {(s.winRate * 100).toFixed(0)}% win
          </div>
          <div className="text-xs font-normal text-cyber-text-faint">
            PF {s.profitFactor.toFixed(2)} · maxDD {fmtUsd(s.maxDrawdown)}
          </div>
        </div>
      </div>

      <Sparkline data={s.equityCurve.length > 1 ? s.equityCurve : [0, 0]} height={44} tone={s.pnl >= 0 ? "green" : "red"} />

      {s.ledger && s.trades > 0 && (
        <div className="mt-3">
          <PnlLines pnl={s.ledger.pnl} compact />
        </div>
      )}

      {/* params */}
      <div className="mt-3 space-y-2">
        {s.params.map((p) => (
          <div key={p.key} className="flex items-center gap-3 text-xs">
            <span className="w-28 text-cyber-text-dim">{p.label}</span>
            <input
              type="range"
              min={p.min}
              max={p.max}
              step={p.step}
              value={p.value}
              onChange={(e) => setStrategyParam(s.id, p.key, Number(e.target.value))}
              className="flex-1 accent-[#00f0ff]"
            />
            <span className="w-12 text-right font-mono text-accent">{p.value}</span>
          </div>
        ))}
      </div>

      {passport && <PassportView s={s} passport={passport} />}

      {/* controls */}
      <div className="mt-4 flex items-center justify-between border-t border-cyber-border pt-3">
        <div className="flex items-center gap-2">
          {paused ? (
            <Button tone="cyan" icon={Play} onClick={() => void setStrategyState(s.id, "paper")}>
              Resume (paper)
            </Button>
          ) : (
            <Button tone="neutral" icon={Pause} onClick={() => void setStrategyState(s.id, "paused")}>
              Pause
            </Button>
          )}
          {!paused && (
            <Button icon={FlaskConical} tone="cyan" onClick={() => void setStrategyState(s.id, "paper")} disabled={s.state === "paper"}>
              Paper
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {live ? (
            <Button tone="red" icon={Radio} onClick={() => void setStrategyState(s.id, "paper")}>
              Disarm live
            </Button>
          ) : (
            <Button tone="red" icon={ready ? Radio : Lock} onClick={() => setConfirm((c) => !c)} disabled={paused || !ready}>
              Arm live…
            </Button>
          )}
        </div>
      </div>

      {!live && !ready && passport?.blockedReason && (
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-cyber-text-dim">
          <Lock size={12} className="mt-0.5 shrink-0" />
          <span>
            Live is locked. {passport.blockedReason} To check that keys and the broker work without a strategy,
            use the connection test on the Live page.
          </span>
        </div>
      )}

      {/* arm-live confirmation */}
      {confirm && !live && ready && (
        <div className="mt-3 rounded-lg border border-danger/40 bg-danger/5 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs text-danger">
            <AlertTriangle size={14} />
            Arming live routes REAL orders using this venue's API keys. Type the strategy name to confirm.
          </div>
          <div className="flex gap-2">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={s.name}
              className="flex-1 rounded border border-cyber-border bg-cyber-surface px-2 py-1 text-sm focus:border-danger focus:outline-none"
            />
            <Button tone="red" onClick={() => void armLive()} disabled={typed.trim() !== s.name}>
              Confirm live
            </Button>
          </div>
          {armErr && <div className="mt-2 text-xs text-danger">{armErr}</div>}
          <div className="mt-2 text-[11px] text-cyber-text-faint">
            Live sends orders only once execution is armed on the Live page, and starts at the venue's smallest
            size until gate 8 is earned. See SAFETY.md.
          </div>
        </div>
      )}
    </Card>
  );
}

/** The eight validation gates as a checklist: green pass, red fail, grey pending, each with its number. */
function PassportView({ s, passport }: { s: StrategyConfig; passport: Passport }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const canRun = researchAvailable();
  const passed = passport.gates.filter((g) => g.status === "pass").length;

  async function check() {
    setBusy(true);
    setErr("");
    try {
      await runValidation(s.id);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-lg border border-cyber-border bg-cyber-surface-2 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <ShieldCheck size={14} className={passport.liveReady ? "text-success" : "text-cyber-text-faint"} />
        <span className="text-xs font-bold uppercase tracking-widest text-cyber-text-dim">Strategy Passport</span>
        <Badge tone={passport.liveReady ? "green" : "neutral"}>{passed} / 8 passed</Badge>
        {passport.stale && <Badge tone="red">parameters changed</Badge>}
        <span className="flex-1" />
        {canRun && (
          <Button tone="cyan" icon={RefreshCw} className="!px-2 !py-0.5 text-xs" onClick={() => void check()} disabled={busy}>
            {busy ? "Checking…" : passport.checkedAt ? "Re-run checks" : "Run checks"}
          </Button>
        )}
      </div>
      <div className="space-y-0.5">
        {passport.gates.map((g) => (
          <GateRow key={g.id} gate={g} open={open === g.id} onToggle={() => setOpen(open === g.id ? null : g.id)} />
        ))}
      </div>
      <div className="mt-2 text-[11px] text-cyber-text-faint">
        {passport.checkedAt
          ? `Gates 1 to 6 checked ${new Date(passport.checkedAt).toLocaleString()} on daily candles.`
          : "Gates 1 to 6 have not been checked yet."}{" "}
        Live needs gates 1 to 7 green; gate 8 is earned at minimum size after arming.
        {!canRun && " Checks need the desktop app or a connected backend."}
      </div>
      {err && <div className="mt-1 text-xs text-danger">{err}</div>}
    </div>
  );
}

function GateRow({ gate, open, onToggle }: { gate: Gate; open: boolean; onToggle: () => void }) {
  const dot = gate.status === "pass" ? "bg-success" : gate.status === "fail" ? "bg-danger" : "bg-cyber-text-faint/50";
  const text = gate.status === "pass" ? "text-success" : gate.status === "fail" ? "text-danger" : "text-cyber-text-faint";
  return (
    <div className="text-xs">
      <button className="flex w-full items-center gap-2 py-0.5 text-left" onClick={onToggle} title={gate.reason}>
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} aria-label={gate.status} />
        <span className="w-4 text-cyber-text-faint">{gate.id}</span>
        <span className="flex-1 text-cyber-text-dim">{gate.name}</span>
        <span className={`font-mono ${text}`}>{gate.value === undefined ? "–" : fmtValue(gate.value, gate.unit)}</span>
      </button>
      {open && (
        <div className="mb-1 ml-8 text-[11px] text-cyber-text-faint">
          <div>
            <span className="text-cyber-text-dim">{gate.measure}:</span> {gate.reason}
          </div>
          {gate.figures && gate.figures.length > 0 && (
            <div className="mt-0.5 flex flex-wrap gap-x-3">
              {gate.figures.map((f) => (
                <span key={f.label}>
                  {f.label} <span className="font-mono text-cyber-text-dim">{fmtValue(f.value, f.unit)}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function fmtValue(v: number, unit: GateUnit): string {
  if (unit === "pct") return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  if (unit === "share") return `${(v * 100).toFixed(0)}%`;
  if (unit === "count") return `${Math.round(v)}`;
  return v.toFixed(Math.abs(v) < 0.1 ? 3 : 2);
}
