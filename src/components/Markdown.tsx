import { Fragment, useMemo, type ReactNode } from "react";
import { parseBlocks, parseInline, studyLink, type Inline } from "../markdown";

/**
 * A lab write-up, rendered from its markdown. Every piece becomes a React
 * element (no HTML from the file reaches the page). Links to another study
 * open that study through `onStudy`; web links open outside the app.
 */
export function Markdown({ source, onStudy }: { source: string; onStudy?: (name: string) => void }) {
  const blocks = useMemo(() => parseBlocks(source), [source]);
  const inline = (s: string) => <Inlines xs={parseInline(s)} onStudy={onStudy} />;
  return (
    <div className="space-y-3 text-sm leading-relaxed text-cyber-text-dim">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h": {
            const cls =
              b.level <= 1
                ? "pt-1 text-base font-semibold text-cyber-text"
                : b.level === 2
                  ? "pt-2 text-[15px] font-semibold text-cyber-text"
                  : "pt-1 text-sm font-semibold text-cyber-text";
            return (
              <div key={i} role="heading" aria-level={Math.min(b.level + 2, 6)} className={cls}>
                {inline(b.text)}
              </div>
            );
          }
          case "p":
            return <p key={i}>{inline(b.text)}</p>;
          case "ul":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5">
                {b.items.map((it, j) => (
                  <li key={j}>{inline(it)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} start={b.start} className="list-decimal space-y-1 pl-5">
                {b.items.map((it, j) => (
                  <li key={j}>{inline(it)}</li>
                ))}
              </ol>
            );
          case "quote":
            return (
              <blockquote key={i} className="border-l-2 border-cyber-border-bright pl-3 text-cyber-text-faint">
                {inline(b.text)}
              </blockquote>
            );
          case "hr":
            return <hr key={i} className="border-cyber-border" />;
          case "code":
            return (
              <pre
                key={i}
                className="overflow-x-auto rounded-lg border border-cyber-border bg-cyber-bg/60 p-3 font-mono text-xs leading-snug text-cyber-text-dim"
              >
                {b.text}
              </pre>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-lg border border-cyber-border">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="bg-cyber-surface-2/60">
                      {b.head.map((h, j) => (
                        <th
                          key={j}
                          scope="col"
                          style={{ textAlign: b.align[j] ?? "left" }}
                          className="whitespace-nowrap px-2.5 py-1.5 font-medium text-cyber-text"
                        >
                          {inline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j} className="border-t border-cyber-border">
                        {b.head.map((_, k) => (
                          <td key={k} style={{ textAlign: b.align[k] ?? "left" }} className="px-2.5 py-1.5 align-top tabular-nums">
                            {inline(r[k] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}

function Inlines({ xs, onStudy }: { xs: Inline[]; onStudy?: (name: string) => void }): ReactNode {
  return (
    <>
      {xs.map((x, i) => {
        switch (x.t) {
          case "text":
            return <Fragment key={i}>{x.v}</Fragment>;
          case "strong":
            return (
              <strong key={i} className="font-semibold text-cyber-text">
                <Inlines xs={x.c} onStudy={onStudy} />
              </strong>
            );
          case "em":
            return (
              <em key={i}>
                <Inlines xs={x.c} onStudy={onStudy} />
              </em>
            );
          case "code": {
            const study = onStudy && /^results\/[\w-]+\.md$/.test(x.v) ? studyLink(x.v) : null;
            const code = <code className="rounded bg-cyber-surface-2 px-1 py-px font-mono text-[0.9em] text-cyber-text">{x.v}</code>;
            return study ? (
              <button key={i} type="button" onClick={() => onStudy!(study)} className="underline-offset-2 hover:underline">
                {code}
              </button>
            ) : (
              <Fragment key={i}>{code}</Fragment>
            );
          }
          case "link": {
            const study = studyLink(x.href);
            if (study && onStudy) {
              return (
                <button key={i} type="button" onClick={() => onStudy(study)} className="text-accent underline-offset-2 hover:underline">
                  <Inlines xs={x.c} onStudy={onStudy} />
                </button>
              );
            }
            if (/^https?:\/\//.test(x.href)) {
              return (
                <a key={i} href={x.href} target="_blank" rel="noreferrer noopener" className="text-accent underline-offset-2 hover:underline">
                  <Inlines xs={x.c} onStudy={onStudy} />
                </a>
              );
            }
            return <Inlines key={i} xs={x.c} onStudy={onStudy} />;
          }
        }
      })}
    </>
  );
}
