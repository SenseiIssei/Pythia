import { useState } from "react";
import { ShieldCheck, Eye, Power, KeyRound, ArrowLeft } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "../design";

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
  tint: string;
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
    tint: "bg-up/10 text-up",
    title: "This is practice money",
    body: [
      "Pythia starts with a pretend balance of 100,000 dollars. Every trade it makes is simulated on real market prices.",
      "Nothing leaves this computer and nothing can be lost. The label at the top says Practice whenever that is true.",
    ],
  },
  {
    icon: Eye,
    tint: "bg-accent/10 text-accent",
    title: "Here is what it is doing",
    body: [
      "It watches crypto, shares and prediction markets, and a few strategies decide when to buy or sell.",
      "Every prediction it makes is written down and later checked against what really happened. Until a strategy has proven itself over weeks, it stays in practice. Home tells you in plain words how it is doing today.",
    ],
  },
  {
    icon: Power,
    tint: "bg-down/10 text-down",
    title: "Here is the stop button",
    body: [
      "\"Stop everything\" on Home stops it from buying anything new, immediately. It can still sell what it already holds.",
      "There is also a Stop button at the top of every page. Pressing it is never wrong.",
    ],
  },
  {
    icon: KeyRound,
    tint: "bg-warn/10 text-warn",
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
    <div className="app-window overflow-y-auto">
      <main className="mx-auto flex min-h-full w-full max-w-xl flex-col px-4 pb-6 pt-6 sm:px-6 sm:pt-12">
        <div className="flex items-center justify-between gap-3">
          {i > 0 ? (
            <button type="button" onClick={() => setI(i - 1)} aria-label="Back" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-ink hover:bg-line">
              <ArrowLeft size={17} aria-hidden />
            </button>
          ) : (
            <span className="h-9 w-9" aria-hidden />
          )}
          <div className="flex gap-1.5" role="img" aria-label={`Step ${i + 1} of ${STEPS.length}`}>
            {STEPS.map((_, k) => (
              <span key={k} className={`h-1.5 rounded-full transition-all ${k === i ? "w-6 bg-ink" : k < i ? "w-1.5 bg-ink" : "w-1.5 bg-line-strong"}`} />
            ))}
          </div>
          <button type="button" onClick={finish} className="rounded-full px-2 py-1 text-[13px] font-semibold text-muted hover:text-ink">
            Skip
          </button>
        </div>

        <div key={i} className="flex-1 animate-slide-up pt-12 sm:pt-16">
          <span className={`mb-6 flex h-16 w-16 items-center justify-center rounded-full ${step.tint}`} aria-hidden>
            <step.icon size={28} />
          </span>
          <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">{step.title}</h1>
          <div className="mt-4 space-y-3 text-[16px] leading-relaxed text-muted">
            {step.body.map((p) => (
              <p key={p}>{p}</p>
            ))}
          </div>
        </div>

        <div className="pt-8">
          <Button full onClick={() => (last ? finish() : setI(i + 1))}>
            {last ? "Start in practice mode" : "Continue"}
          </Button>
          <p className="mt-3 text-center text-[13px] text-faint">
            {i + 1} of {STEPS.length}
          </p>
        </div>
      </main>
    </div>
  );
}
