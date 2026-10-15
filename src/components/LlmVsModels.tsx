import { Badge, List } from "../design";
import { More, Row, Section, num, share } from "../pagekit";
import { Markdown } from "./Markdown";
import { brierGap, usd, vsRows, type AiReport } from "../aiBudget";

const fmtP = (p: number) => `${Math.round(p * 100)} %`;

/**
 * The daily AI brief's 7-day calls scored against the base rate and the
 * momentum rule, the latest brief, and the weekly review. Shadow only.
 */
export function LlmVsModels({ r }: { r: AiReport }) {
  const s = r.scores;
  const brief = r.brief;
  if (!s && !brief && !r.weekly) return null;
  const rows = s ? vsRows(s) : [];
  const mom = s ? brierGap(s.vs.momentum) : null;
  const base = s ? brierGap(s.vs.base) : null;

  return (
    <Section
      title="LLM vs our models"
      hint="Each day a cheap Claude call gives a 7-day up-or-down probability for BTC, ETH and the autopilots' coins. Every call is written down first and scored a week later, next to the base rate and the lab's momentum rule. Lower Brier is better."
      right={<Badge tone="accent">shadow, never traded</Badge>}
    >
      {s && (
        <>
          <List>
            {rows.map((x) => (
              <Row
                key={x.key}
                label={
                  <span className="font-semibold">
                    {x.label}
                    {x.best && x.n > 0 ? " · best so far" : ""}
                  </span>
                }
                sub={<span className="tabular">{x.sub}</span>}
                value={x.brier === null ? "not yet" : num(x.brier, 4)}
                valueSub={
                  x.n > 0 ? (
                    <span className="tabular">
                      log loss {x.logloss === null ? "n/a" : num(x.logloss, 3)} · hit {x.hitRate === null ? "n/a" : share(x.hitRate)} · {x.n}
                    </span>
                  ) : undefined
                }
                tone={x.best && x.n > 0 ? "up" : "plain"}
                help="Brier score: the mean squared gap between the probability and what happened (1 up, 0 not). 0.25 is a coin flip at 50 %."
              />
            ))}
          </List>
          <p className="mt-2 text-[13px] text-muted">
            {s.verdict} {mom && base ? `LLM Brier minus momentum rule ${mom}, minus base rate ${base}.` : ""} {s.pending} waiting for their week.
          </p>
        </>
      )}

      {brief && (
        <div className="mt-4">
          <div className="mb-1 text-[15px] font-semibold text-ink">
            Brief of {brief.date}
            <span className="ml-2 text-[13px] font-normal text-muted">
              {brief.model ?? "Claude"}
              {brief.costUsd !== null ? `, ${usd(brief.costUsd)}` : ""}
              {brief.batch ? ", batch" : ""}
            </span>
          </div>
          {brief.summary.length > 0 && (
            <ul className="mb-2 list-disc space-y-0.5 pl-5 text-[14px] text-ink">
              {brief.summary.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
          <More title={`${brief.predictions.length} seven-day calls`}>
            <List>
              {brief.predictions.map((p) => (
                <Row
                  key={p.coin}
                  label={<span className="font-semibold">{p.coin}</span>}
                  sub={p.reason}
                  value={fmtP(p.p_llm)}
                  valueSub={
                    <span className="tabular">
                      base {fmtP(p.p_base)} · momentum {fmtP(p.p_momentum)} · until {p.resolve_day}
                    </span>
                  }
                />
              ))}
            </List>
          </More>
          {brief.problems.length > 0 && <p className="mt-1 text-[13px] text-warn">Dropped from the answer: {brief.problems.join("; ")}.</p>}
        </div>
      )}

      {r.weekly && (
        <div className="mt-4">
          <More title={`Weekly review${r.weekly.updatedMs ? `, ${new Date(r.weekly.updatedMs).toLocaleDateString()}` : ""}: three proposed experiments`}>
            <div className="fl">
              <Markdown source={r.weekly.markdown} />
            </div>
          </More>
        </div>
      )}
    </Section>
  );
}
