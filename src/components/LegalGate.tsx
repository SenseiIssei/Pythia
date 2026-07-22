import { useState } from "react";
import { motion } from "framer-motion";
import { ShieldAlert, Check } from "lucide-react";

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
  "Automated trading and prediction-market betting can lose ALL the money I commit — quickly, and while I'm away.",
  "I am solely responsible for the legality of my use where I live (e.g. Polymarket is geoblocked for US persons).",
  "Pythia stays in paper (simulated) mode until I deliberately arm a strategy live with my own API keys.",
  "My API keys are mine to secure; a leaked key can drain an account.",
];

export function LegalGate({ onAccept }: { onAccept: () => void }) {
  const [checked, setChecked] = useState<boolean[]>(TERMS.map(() => false));
  const all = checked.every(Boolean);

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
    <div className="app-window grid-bg flex items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-2xl rounded-xl border border-danger/40 bg-cyber-surface p-6 glow-red"
      >
        <div className="mb-4 flex items-center gap-3">
          <ShieldAlert className="text-danger" size={26} />
          <div>
            <h1 className="text-xl font-bold text-glow-red">Read this before you continue</h1>
            <p className="text-xs text-cyber-text-dim">Pythia can place real orders with real money. Acknowledge each point to proceed.</p>
          </div>
        </div>

        <div className="space-y-2">
          {TERMS.map((t, i) => (
            <button
              key={i}
              onClick={() => setChecked((c) => c.map((v, j) => (j === i ? !v : v)))}
              className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left text-sm transition-colors ${
                checked[i] ? "border-success/40 bg-success/5 text-cyber-text" : "border-cyber-border bg-cyber-surface-2 text-cyber-text-dim hover:border-cyber-border-bright"
              }`}
            >
              <span
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                  checked[i] ? "border-success bg-success/20 text-success" : "border-cyber-border-bright"
                }`}
              >
                {checked[i] && <Check size={12} />}
              </span>
              {t}
            </button>
          ))}
        </div>

        <div className="mt-5 flex items-center justify-between">
          <a className="text-xs text-accent hover:underline" href="https://github.com/SenseiIssei/Pythia/blob/main/SAFETY.md" target="_blank" rel="noreferrer">
            Read the full SAFETY.md →
          </a>
          <button
            onClick={accept}
            disabled={!all}
            className={`rounded-lg border px-4 py-2 text-sm font-bold transition-colors ${
              all ? "border-accent/50 bg-accent/10 text-accent glow-cyan hover:bg-accent/20" : "cursor-not-allowed border-cyber-border text-cyber-text-faint"
            }`}
          >
            I understand — enter Pythia (paper mode)
          </button>
        </div>
      </motion.div>
    </div>
  );
}
