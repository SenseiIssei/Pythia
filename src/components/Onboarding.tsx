import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldCheck, Eye, Power, KeyRound, ArrowRight, ArrowLeft } from "lucide-react";
import type { LucideIcon } from "lucide-react";

const DONE_KEY = "pythia.onboarding.v1";

export function hasSeenOnboarding(): boolean {
  try {
    return localStorage.getItem(DONE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Show the walkthrough again (Settings offers this). */
export function resetOnboarding(): void {
  try {
    localStorage.removeItem(DONE_KEY);
  } catch {
    /* ignore */
  }
}

interface Step {
  icon: LucideIcon;
  tone: string;
  title: string;
  body: string[];
}

/**
 * Four screens for someone who has never traded, in the order the questions
 * come up: is this real money, what is it doing, how do I stop it, and how
 * would it ever touch real money (and why not yet).
 */
const STEPS: Step[] = [
  {
    icon: ShieldCheck,
    tone: "text-success",
    title: "This is practice money",
    body: [
      "Pythia starts with a pretend balance of 100,000 dollars. Every trade it makes is simulated on real market prices.",
      "Nothing leaves this computer and nothing can be lost. The green banner at the top says so whenever that is true.",
    ],
  },
  {
    icon: Eye,
    tone: "text-accent",
    title: "Here is what it is doing",
    body: [
      "It watches crypto, shares and prediction markets, and a few strategies decide when to buy or sell.",
      "Every prediction it makes is written down and later checked against what really happened. Until a strategy has proven itself over weeks, it stays in practice. The Home page tells you in plain words how it is doing today.",
    ],
  },
  {
    icon: Power,
    tone: "text-danger",
    title: "Here is the stop button",
    body: [
      "\"Stop everything\" on the Home page stops it from buying anything new, immediately. It can still sell what it already holds.",
      "There is also a KILL button in the top bar, on every page. Pressing it is never wrong.",
    ],
  },
  {
    icon: KeyRound,
    tone: "text-warning",
    title: "How it could ever use real money, and why not yet",
    body: [
      "Real money needs your own broker keys, a typed confirmation, and a strategy that has passed all of its checks, including 30 days of practice. It cannot happen by accident.",
      "Most automated trading loses money to fees. Pythia is built to prove a strategy before trusting it, and to say so plainly when nothing has earned that yet. Only ever use money you could lose entirely.",
    ],
  },
];

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [i, setI] = useState(0);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  function finish() {
    try {
      localStorage.setItem(DONE_KEY, "1");
    } catch {
      /* ignore */
    }
    onDone();
  }

  return (
    <div className="app-window grid-bg flex items-start justify-center overflow-y-auto p-4 sm:items-center sm:p-6">
      <div className="w-full max-w-xl rounded-xl border border-cyber-border bg-cyber-surface p-5 sm:p-6">
        <div className="mb-2 flex gap-1.5" role="img" aria-label={`Step ${i + 1} of ${STEPS.length}`}>
          {STEPS.map((_, k) => (
            <div key={k} className={`h-1 flex-1 rounded-full ${k <= i ? "bg-accent" : "bg-cyber-surface-2"}`} />
          ))}
        </div>
        <div className="mb-5 font-mono text-[11px] text-cyber-text-faint">
          {i + 1} of {STEPS.length}
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={i}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.18 }}
          >
            <step.icon size={30} aria-hidden className={`mb-3 ${step.tone}`} />
            <h1 className="mb-3 font-mono text-xl font-bold text-cyber-text">{step.title}</h1>
            <div className="space-y-3 text-sm leading-relaxed text-cyber-text-dim">
              {step.body.map((p) => (
                <p key={p}>{p}</p>
              ))}
            </div>
          </motion.div>
        </AnimatePresence>
        <div className="mt-6 flex items-center justify-between">
          <button
            type="button"
            onClick={finish}
            className="rounded px-1 text-xs text-cyber-text-faint hover:text-cyber-text"
          >
            Skip the introduction
          </button>
          <div className="flex gap-2">
            {i > 0 && (
              <button
                type="button"
                onClick={() => setI(i - 1)}
                className="flex items-center gap-1.5 rounded-lg border border-cyber-border px-3 py-1.5 text-sm text-cyber-text-dim hover:text-cyber-text"
              >
                <ArrowLeft size={14} /> Back
              </button>
            )}
            <button
              type="button"
              onClick={() => (last ? finish() : setI(i + 1))}
              className="flex items-center gap-1.5 rounded-lg border border-accent/50 bg-accent/10 px-4 py-1.5 text-sm font-bold text-accent hover:bg-accent/20"
            >
              {last ? "Start in practice mode" : "Next"} {!last && <ArrowRight size={14} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
