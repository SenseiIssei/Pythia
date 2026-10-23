import { useState } from "react";
import { Check, ExternalLink, ShieldAlert } from "lucide-react";
import { Button, Screen } from "../design";

const ACK_KEY = "pythia.legal.ack.v1";

export function hasAcceptedLegal(): boolean {
  try {
    return localStorage.getItem(ACK_KEY) === "1";
  } catch {
    return false;
  }
}

const TERMS = [
  "Pythia is software, not financial advice. Nothing it shows is a recommendation to buy, sell, or bet.",
  "Automated trading and prediction-market betting can lose ALL the money I commit, quickly, and while I'm away.",
  "I am solely responsible for the legality of my use where I live (e.g. Polymarket is geoblocked for US persons).",
  "Pythia stays in paper (simulated) mode until I deliberately arm a strategy live with my own API keys.",
  "My API keys are mine to secure; a leaked key can drain an account.",
];

export function LegalGate({ onAccept }: { onAccept: () => void }) {
  const [checked, setChecked] = useState<boolean[]>(TERMS.map(() => false));
  const all = checked.every(Boolean);
  const count = checked.filter(Boolean).length;

  function accept() {
    if (!all) return;
    try {
      localStorage.setItem(ACK_KEY, "1");
    } catch {
      /* ignore */
    }
    onAccept();
  }

  return (
    <Screen label="Before you start">
      <main className="mx-auto flex w-full max-w-xl flex-col px-4 pb-10 pt-10 sm:px-6 sm:pt-16">
        <span className="mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-down/10 text-down" aria-hidden>
          <ShieldAlert size={26} />
        </span>
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">Before you start</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">
          Pythia can place real orders with real money. Tick each point to continue. It starts with practice money either way.
        </p>

        <fieldset className="mt-7">
          <legend className="sr-only">Points to confirm</legend>
          <div className="divide-y divide-line rounded-card border border-line bg-surface">
            {TERMS.map((t, i) => (
              <button
                key={i}
                type="button"
                role="checkbox"
                aria-checked={checked[i]}
                onClick={() => setChecked((c) => c.map((v, j) => (j === i ? !v : v)))}
                className="flex w-full items-start gap-3.5 px-4 py-4 text-left first:rounded-t-card last:rounded-b-card hover:bg-surface-2"
              >
                <span
                  aria-hidden
                  className={`mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
                    checked[i] ? "border-primary bg-primary text-on-primary" : "border-line-strong"
                  }`}
                >
                  {checked[i] && <Check size={13} strokeWidth={3} />}
                </span>
                <span className={`text-[15px] leading-snug ${checked[i] ? "text-ink" : "text-muted"}`}>{t}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="mt-7 space-y-4">
          <Button full onClick={accept} disabled={!all}>
            {all ? "I understand, start in practice mode" : `Tick all ${TERMS.length} points (${count} of ${TERMS.length})`}
          </Button>
          <a
            className="mx-auto flex w-fit items-center gap-1.5 rounded text-[13px] font-medium text-accent hover:underline"
            href="https://github.com/SenseiIssei/Pythia/blob/main/SAFETY.md"
            target="_blank"
            rel="noreferrer"
          >
            Read the full safety notes <ExternalLink size={13} aria-hidden />
          </a>
        </div>
      </main>
    </Screen>
  );
}
