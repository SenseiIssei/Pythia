import { Fragment, useMemo, type ReactNode } from "react";
import { parseBlocks, parseInline, studyLink, type Inline } from "../markdown";

/**
 * A lab write-up, rendered from its markdown. Every piece becomes a React
 * element (no HTML from the file reaches the page). Links to another study
 * open that study through `onStudy`; web links open outside the app.
 *
 * Styled with the calm flows tokens (design/flows/flows.css), so it belongs
 * inside an element with the `fl` class.
 */
export function Markdown({ source, onStudy }: { source: string; onStudy?: (name: string) => void }) {
  const blocks = useMemo(() => parseBlocks(source), [source]);
  const inline = (s: string) => <Inlines xs={parseInline(s)} onStudy={onStudy} />;
  return (
    <div className="space-y-3 text-[15px] leading-relaxed">
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h": {
            const cls =
              b.level <= 1
                ? "pt-1 text-xl font-bold tracking-tight"
                : b.level === 2
                  ? "pt-3 text-lg font-semibold tracking-tight"
                  : "pt-2 text-[15px] font-semibold";
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
              <blockquote key={i} className="fl-muted fl-line border-l-2 pl-3">
                {inline(b.text)}
              </blockquote>
            );
          case "hr":
            return <hr key={i} className="fl-line" />;
          case "code":
            return (
              <pre key={i} className="fl-surface-2 overflow-x-auto rounded-xl p-3 font-mono text-xs leading-snug">
                {b.text}
              </pre>
            );
          case "table":
            return (
              <div key={i} className="fl-line overflow-x-auto rounded-xl border">
                <table className="fl-num w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="fl-surface-2">
                      {b.head.map((h, j) => (
                        <th key={j} scope="col" style={{ textAlign: b.align[j] ?? "left" }} className="whitespace-nowrap px-2.5 py-2 font-semibold">
                          {inline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j} className="fl-line border-t">
                        {b.head.map((_, k) => (
                          <td key={k} style={{ textAlign: b.align[k] ?? "left" }} className="px-2.5 py-1.5 align-top">
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
              <strong key={i} className="font-semibold">
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
            const code = <code className="fl-surface-2 rounded px-1 py-px font-mono text-[0.88em]">{x.v}</code>;
            return study ? (
              <button key={i} type="button" onClick={() => onStudy!(study)} className="fl-focus underline underline-offset-2">
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
                <button key={i} type="button" onClick={() => onStudy(study)} className="fl-focus font-medium underline underline-offset-2">
                  <Inlines xs={x.c} onStudy={onStudy} />
                </button>
              );
            }
            if (/^https?:\/\//.test(x.href)) {
              return (
                <a key={i} href={x.href} target="_blank" rel="noreferrer noopener" className="fl-focus font-medium underline underline-offset-2">
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
