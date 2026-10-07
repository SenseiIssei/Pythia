import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FileDown } from "lucide-react";
import { Button, Card, fmtUsd } from "./ui";
import { liveMode } from "../live";
import { serverUrl } from "../engine/serverEngine";

interface YearSummary {
  year: number;
  shortTerm: number;
  longTerm: number;
  disposals: number;
  fees: number;
}

interface TaxSummary {
  years: YearSummary[];
  open: Record<string, number>;
  unmatchedSells: number;
  fills: number;
  damagedLines: number;
}

/**
 * The tax record: every real fill, kept in an append-only file next to the
 * app's data. A FIFO preview here; the CoinTracking CSV is what Blockpit,
 * CoinTracking and similar tools import, and their numbers are the ones that count.
 */
export function TaxCard() {
  const mode = liveMode();
  const [s, setS] = useState<TaxSummary | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (mode === "native") {
      invoke<TaxSummary>("tax_export", { cointracking: false }).then(setS).catch((e) => setNote(String(e)));
    } else if (mode === "server") {
      fetch(`${serverUrl()}/api/tax`)
        .then((r) => r.json())
        .then(setS)
        .catch((e) => setNote(String(e)));
    }
  }, [mode]);

  if (mode === "none") return null;

  async function exportCsv() {
    if (mode === "native") {
      try {
        const path = await invoke<string>("tax_save_csv");
        setNote(`Saved to ${path}`);
      } catch (e) {
        setNote(`Could not save: ${String(e)}`);
      }
    }
  }

  return (
    <Card
      title="Tax record"
      right={
        mode === "native" ? (
          <Button tone="neutral" size="sm" icon={FileDown} onClick={() => void exportCsv()}>
            CoinTracking CSV
          </Button>
        ) : (
          <a
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyber-border-bright px-2.5 py-1 text-xs text-accent hover:bg-cyber-surface-2"
            href={`${serverUrl()}/api/tax?format=cointracking`}
          >
            <FileDown size={13} aria-hidden /> CoinTracking CSV
          </a>
        )
      }
    >
      <p className="text-xs leading-relaxed text-cyber-text-dim">
        Every real fill is kept in an append-only file. The CSV imports into Blockpit, CoinTracking and similar tools,
        which convert to euros at each trade's rate. Below is a first-in, first-out preview in dollars: for crypto in
        Germany, gains on lots held over a year are tax-free, shorter ones count against the 1,000 EUR yearly limit.
        Dates, years and holding periods use German local time. A preview, not tax advice.
      </p>
      {s && s.fills === 0 && <p className="mt-2 text-sm text-cyber-text-dim">No real fills yet. Paper trades are never recorded here.</p>}
      {!s && !note && <p className="mt-2 text-xs text-cyber-text-faint">Reading the record.</p>}
      {s && s.years.length > 0 && (
        <div className="-mx-1 overflow-x-auto px-1">
        <table className="mt-3 w-full min-w-[480px] font-mono text-sm tabular-nums">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-cyber-text-faint">
              <th className="py-1">Year</th>
              <th className="py-1 text-right">Held up to a year</th>
              <th className="py-1 text-right">Held over a year</th>
              <th className="py-1 text-right">Sales</th>
              <th className="py-1 text-right">Fees</th>
            </tr>
          </thead>
          <tbody>
            {s.years.map((y) => (
              <tr key={y.year} className="border-t border-cyber-border">
                <td className="py-1">{y.year}</td>
                <td className={`py-1 text-right ${y.shortTerm >= 0 ? "text-success" : "text-danger"}`}>{fmtUsd(y.shortTerm)}</td>
                <td className="py-1 text-right text-cyber-text-dim">{fmtUsd(y.longTerm)}</td>
                <td className="py-1 text-right">{y.disposals}</td>
                <td className="py-1 text-right text-cyber-text-dim">{fmtUsd(y.fees)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {s && s.unmatchedSells > 0 && (
        <p className="mt-2 text-xs text-warning">
          {s.unmatchedSells} sale(s) had no matching purchase in the record (bought before Pythia or elsewhere), so their
          gains are not in this preview. The tax tool needs those purchases too.
        </p>
      )}
      {s && s.damagedLines > 0 && (
        <p className="mt-2 text-xs text-danger">{s.damagedLines} damaged line(s) in the record were skipped.</p>
      )}
      {note && <p className="mt-2 text-xs text-cyber-text-dim">{note}</p>}
    </Card>
  );
}
