// The Lab page's research factory panel: the two factories (F3 pump.fun, F2
// small wallets) with their ledgers' sizes and bars, the night's best candidate
// and its held-back result, the paper books they run with their wallets in EUR;
// the model zoo's pick per label; the allocator's posterior per strategy and
// what it would pick (it never steers the live bot). Paper only, read only.

import { Badge, Chip, List } from "../design";
import { Row, Section, plural } from "../pagekit";
import { ago } from "../labFeeds";
import { sharePct } from "../pumpfunLab";
import { sol } from "../pumpfunLive";
import { armRows, euro, factoryViews, zooPicks, type FactoryView, type LabFactory as Data } from "../labFactory";

const toneText = (v: number | null | undefined) => (v == null || v === 0 ? "text-ink" : v > 0 ? "text-up" : "text-down");
const pct0 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "n/a" : `${Math.round(v * 100)} %`);

function FactoryItem({ f, now }: { f: FactoryView; now: number }) {
  const r = f.report;
  return (
    <div className="py-3" data-factory={f.code}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 truncate text-[15px] font-semibold text-ink">{f.name}</span>
        <Chip tone={r ? "neutral" : "warn"}>{r ? (r.updated_ms ? ago(r.updated_ms, now) : r.night ?? "report") : "no report yet"}</Chip>
      </div>
      {!r ? (
        <p className="mt-1 text-[13px] text-muted">This factory has not written a report to the lab's data folder yet.</p>
      ) : (
        <>
          <div className="mt-1 divide-y divide-line">
            <Row
              label="Ledger"
              value={plural(r.trials_ever ?? 0, "trial")}
              valueSub={`${r.trials_tonight ?? 0} last night`}
              help="Every trial the factory ever ran stays in its ledger; the bar rises with it."
            />
            <Row
              label="Bar"
              value={r.bar?.sharpe == null ? "n/a" : `Sharpe ${r.bar.sharpe.toFixed(3)}`}
              valueSub={`p ≥ ${r.bar?.p ?? 0.95}, ${r.bar?.min_entries ?? 20}+ entries`}
              help="The Sharpe per entry the best of that many trials reaches by luck alone; a candidate has to be clearly above it."
            />
            <Row
              label="Best new candidate"
              value={f.best ? f.best.id : "none"}
              valueSub={f.best?.median == null ? undefined : `median ${sol(f.best.median, false, 3)} after 30 days`}
              sub={f.best?.label ?? undefined}
            />
            <Row
              label="Held back"
              value={f.held ? sol(f.held.pnl_sol, true, 3) : "not held back"}
              tone={f.held?.pnl_sol == null ? undefined : f.held.pnl_sol > 0 ? "up" : f.held.pnl_sol < 0 ? "down" : undefined}
              valueSub={f.held ? `median ${sol(f.held.median, false, 3)} · ${plural(f.held.entries ?? 0, "entry", "entries")} at 0.1 SOL` : undefined}
            />
            <Row label="Model settings adopted" value={(r.adopted ?? []).length ? (r.adopted ?? []).join(", ") : "none"} />
          </div>
          <h4 className="mt-2 text-[13px] font-semibold text-muted">
            Paper books{(r.winners ?? []).length ? ` · winners tonight ${(r.winners ?? []).join(", ")}` : ""}
          </h4>
          {f.books.length === 0 ? (
            <p className="mt-1 text-[13px] text-muted">No paper book running.</p>
          ) : (
            <ul className="mt-1 divide-y divide-line text-[13px]">
              {f.books.map((b) => (
                <li key={b.book} className="flex items-baseline justify-between gap-3 py-1.5" data-book={b.book}>
                  <span className="min-w-0 truncate">
                    <span className="font-code text-ink">{b.book}</span>
                    {b.proposed ? " · proposed" : ""}
                    {b.sizing ? <span className="text-muted"> · {b.sizing}</span> : null}
                  </span>
                  <span className="tabular shrink-0">
                    {euro(b.eurNow)} <span className="text-muted">· {sol(b.sol, false, 3)}</span>{" "}
                    <span className={toneText(b.pnl_sol)}>{sol(b.pnl_sol, true, 3)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** The panel itself; the Lab page reads the data and polls it. */
export function LabFactory({ data, err, now }: { data: Data | null; err: string; now: number }) {
  const facs = factoryViews(data);
  const arms = armRows(data?.allocator);
  const picks = zooPicks(data);
  const al = data?.allocator;
  return (
    <Section
      title="Forschungs-Fabrik"
      hint="The nightly searches for strategies (F3 pump.fun, F2 small wallets), the model zoo's choices and the allocator's view of the paper strategies. Paper only; nothing here steers the live bot."
    >
      {err && !data && <p className="text-sm text-muted">{err}</p>}
      {data && !data.found && <p className="text-sm text-muted">No factory, zoo or allocator report in the lab's data folder yet.</p>}
      {data?.found && (
        <div className="space-y-4">
          <List>
            {facs.map((f) => (
              <FactoryItem key={f.code} f={f} now={now} />
            ))}
          </List>

          <div>
            <h3 className="text-[13px] font-semibold text-muted">Model zoo (A1): the pick per label</h3>
            {picks.length === 0 ? (
              <p className="mt-1 text-sm text-muted">No zoo report yet.</p>
            ) : (
              <div className="mt-1 divide-y divide-line">
                {picks.map((p) => (
                  <Row key={p.label} label={p.label} value={p.pick ?? "none"} valueSub={p.days == null ? undefined : `${plural(p.days, "day")} scored`} sub={p.changed ?? undefined} />
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-[13px] font-semibold text-muted">
              Allocator (A1): {al ? `would pick ${al.choice ?? "none (every strategy guarded)"}` : "no report yet"}
              {al?.live_rule ? ` · the live bot keeps ${al.live_rule}` : ""}
            </h3>
            {arms.length > 0 && (
              <ul className="mt-1 divide-y divide-line text-[13px]">
                {arms.map((a) => (
                  <li key={a.name} className="py-1.5" data-arm={a.name}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 truncate font-code text-ink">
                        {a.name} {a.chosen && <Badge tone="good">pick</Badge>} {a.live && <Badge>live</Badge>} {a.guarded && <Badge tone="bad">guarded</Badge>}
                      </span>
                      <span className="tabular shrink-0">
                        P(best) {pct0(a.p_best)} · weight {pct0(a.weight)}
                      </span>
                    </div>
                    <div className="text-muted">
                      Posterior daily growth <span className={`tabular ${toneText(a.posterior_mean)}`}>{sharePct(a.posterior_mean, 2)}</span>
                      {a.posterior_sd != null && Number.isFinite(a.posterior_sd) ? ` ± ${(a.posterior_sd * 100).toFixed(2)} %` : ""} over {plural(a.days ?? 0, "day")}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
