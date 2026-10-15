import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FileDown } from "lucide-react";
import { Button, List, Notice, changeTone as toneOf, money as usd } from "../design";
import { LoadingRows, More, Row, Section, plural } from "../pagekit";
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
    <Section
      title="Tax record"
      hint="Every real fill is kept in a file that is only ever added to. A first-in, first-out preview in dollars; a preview, not tax advice."
      right={
        mode === "native" ? (
          <Button variant="secondary" icon={FileDown} onClick={() => void exportCsv()}>
            CoinTracking CSV
          </Button>
        ) : (
          <a className="inline-flex min-h-[46px] items-center justify-center gap-2 rounded-full bg-surface-2 px-5 text-[15px] font-semibold text-ink hover:bg-line" href={`${serverUrl()}/api/tax?format=cointracking`}>
            <FileDown size={16} aria-hidden /> CoinTracking CSV
          </a>
        )
      }
    >
      {!s && !note && <LoadingRows rows={2} label="Reading the record" />}
      {s && s.fills === 0 && <p className="text-[15px] text-muted">No real fills yet. Paper trades are never recorded here.</p>}
      {s && s.years.length > 0 && (
        <List>
          {s.years.map((y) => (
            <Row
              key={y.year}
              label={String(y.year)}
              sub={`${plural(y.disposals, "sale")} · fees ${usd(y.fees)} · held over a year ${usd(y.longTerm)}`}
              value={usd(y.shortTerm)}
              tone={toneOf(y.shortTerm)}
              valueSub="held up to a year"
              help="Gains on lots held up to a year count against the yearly limit; lots held longer are shown under the year."
            />
          ))}
        </List>
      )}
      {s && s.unmatchedSells > 0 && (
        <div className="mt-2">
          <Notice tone="warning">
            {plural(s.unmatchedSells, "sale")} had no matching purchase in the record (bought before Pythia or elsewhere), so
            their gains are not in this preview. The tax tool needs those purchases too.
          </Notice>
        </div>
      )}
      {s && s.damagedLines > 0 && (
        <div className="mt-2">
          <Notice tone="danger">{plural(s.damagedLines, "damaged line")} in the record were skipped.</Notice>
        </div>
      )}
      {note && <p className="mt-2 break-words text-sm text-muted">{note}</p>}
      <div className="mt-2">
        <More title="How the preview counts">
          <p className="text-sm leading-relaxed text-muted">
            The CSV imports into Blockpit, CoinTracking and similar tools, which convert to euros at each trade's rate.
            For crypto in Germany, gains on lots held over a year are tax-free, shorter ones count against the 1,000 EUR
            yearly limit. Dates, years and holding periods use German local time.
          </p>
        </More>
      </div>
    </Section>
  );
}
