// A small markdown reader for the lab's write-ups (research/lab/results/*.md).
//
// The lab writes plain markdown: headings, paragraphs, bullet lists, pipe
// tables, fenced code and the odd bold or link. This turns it into blocks and
// inline pieces that the renderer (components/Markdown.tsx) maps to React
// elements, so nothing from a file is ever injected as HTML.

export type Inline =
  | { t: "text"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "code"; v: string }
  | { t: "link"; href: string; c: Inline[] };

export type Align = "left" | "right" | "center" | null;

export type Block =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "ul"; items: string[] }
  | { t: "ol"; items: string[]; start: number }
  | { t: "table"; head: string[]; align: Align[]; rows: string[][] }
  | { t: "code"; lang: string; text: string }
  | { t: "quote"; text: string }
  | { t: "hr" };

const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d+)[.)]\s+(.*)$/;
const DIVIDER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** One table row's cells; `\|` stays a literal bar. */
export function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  let inCode = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (c === "`") {
      inCode = !inCode;
      cur += c;
    } else if (c === "|" && !inCode) {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += c;
    }
  }
  cells.push(cur.trim());
  return cells;
}

function alignOf(cell: string): Align {
  const c = cell.trim();
  const l = c.startsWith(":");
  const r = c.endsWith(":");
  return l && r ? "center" : r ? "right" : l ? "left" : null;
}

function isTableStart(lines: string[], i: number): boolean {
  return lines[i].includes("|") && i + 1 < lines.length && lines[i + 1].includes("-") && DIVIDER.test(lines[i + 1]);
}

function startsBlock(lines: string[], i: number): boolean {
  const l = lines[i];
  return (
    FENCE.test(l) || HEADING.test(l) || RULE.test(l) || BULLET.test(l) || NUMBERED.test(l) || /^\s*>/.test(l) || isTableStart(lines, i)
  );
}

/** The blocks of a markdown text, top to bottom. HTML comments are dropped. */
export function parseBlocks(md: string): Block[] {
  const lines = md.replace(/\r\n?/g, "\n").replace(/<!--[\s\S]*?-->/g, "").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(fence[1]) && FENCE.test(lines[i]))) body.push(lines[i++]);
      i++; // the closing fence, or past the end
      out.push({ t: "code", lang: fence[2], text: body.join("\n") });
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      out.push({ t: "h", level: h[1].length, text: h[2] });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ t: "hr" });
      i++;
      continue;
    }
    if (isTableStart(lines, i)) {
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map(alignOf);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(splitRow(lines[i++]));
      out.push({ t: "table", head, align, rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const num = NUMBERED.exec(line);
    if (bullet || num) {
      const ordered = !bullet;
      const items: string[] = [];
      while (i < lines.length) {
        const l = lines[i];
        const b = BULLET.exec(l);
        const n = NUMBERED.exec(l);
        if ((ordered && n) || (!ordered && b)) {
          items.push((ordered ? n![3] : b![2]).trim());
        } else if (l.trim() && /^\s+/.test(l) && items.length && !startsBlock(lines, i)) {
          items[items.length - 1] += ` ${l.trim()}`; // a wrapped item
        } else if (l.trim() && (b || n) && items.length) {
          items.push((b ? b[2] : n![3]).trim()); // a nested item of the other kind, flattened
        } else {
          break;
        }
        i++;
      }
      out.push(ordered ? { t: "ol", items, start: Number(num![2]) || 1 } : { t: "ul", items });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push({ t: "quote", text: body.join(" ").trim() });
      continue;
    }
    const para: string[] = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) para.push(lines[i++].trim());
    out.push({ t: "p", text: para.join(" ") });
  }
  return out;
}

const isWord = (c: string | undefined) => c !== undefined && /[\p{L}\p{N}]/u.test(c);

function pushText(out: Inline[], v: string) {
  const last = out[out.length - 1];
  if (last && last.t === "text") last.v += v;
  else if (v) out.push({ t: "text", v });
}

/** Bold, italics, inline code and links. Anything unclosed stays as text. */
export function parseInline(s: string): Inline[] {
  const out: Inline[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === "\\" && i + 1 < s.length && /[\\`*_[\]()|#]/.test(s[i + 1])) {
      pushText(out, s[i + 1]);
      i += 2;
      continue;
    }
    if (c === "`") {
      const end = s.indexOf("`", i + 1);
      if (end > i) {
        out.push({ t: "code", v: s.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    if (s.startsWith("**", i) || s.startsWith("__", i)) {
      const mark = s.slice(i, i + 2);
      const end = s.indexOf(mark, i + 2);
      if (end > i + 2) {
        out.push({ t: "strong", c: parseInline(s.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
    }
    if ((c === "*" || c === "_") && s[i + 1] && s[i + 1] !== " " && s[i + 1] !== c && !(c === "_" && isWord(s[i - 1]))) {
      let end = -1;
      for (let j = i + 2; j < s.length; j++) {
        if (s[j] === c && s[j - 1] !== " " && s[j + 1] !== c && !(c === "_" && isWord(s[j + 1]))) {
          end = j;
          break;
        }
      }
      if (end > i) {
        out.push({ t: "em", c: parseInline(s.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    if (c === "[") {
      const m = /^\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/.exec(s.slice(i));
      if (m) {
        out.push({ t: "link", href: m[2], c: parseInline(m[1]) });
        i += m[0].length;
        continue;
      }
    }
    pushText(out, c);
    i++;
  }
  return out;
}

/** The plain text of an inline string: markup removed, for one-line summaries. */
export function plainText(s: string): string {
  const walk = (xs: Inline[]): string =>
    xs.map((x) => (x.t === "text" || x.t === "code" ? x.v : walk(x.c))).join("");
  return walk(parseInline(s)).replace(/\s+/g, " ").trim();
}

/** `results/<name>.md` or `<name>.md` as a study name; null for anything else. */
export function studyLink(href: string): string | null {
  if (href.startsWith("study:")) return href.slice(6) || null;
  if (/^[a-z]+:/i.test(href)) return null;
  const m = /(?:^|\/)([\w-]+)\.md$/.exec(href);
  return m ? m[1] : null;
}
