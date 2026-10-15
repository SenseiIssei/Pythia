import { describe, expect, it } from "vitest";
import { parseBlocks, parseInline, plainText, splitRow, studyLink } from "./markdown";

describe("parseBlocks", () => {
  it("reads headings, paragraphs, lists, tables, code and rules", () => {
    const md = [
      "# Title #",
      "<!-- generated below; edit above this line only -->",
      "",
      "First line",
      "wraps here.",
      "",
      "- one",
      "  continued",
      "- two",
      "  - nested",
      "",
      "3. third",
      "4. fourth",
      "",
      "| a | b |",
      "|---|--:|",
      "| 1 | `x|y` |",
      "| 2 |",
      "",
      "```text",
      "| not a table |",
      "```",
      "---",
      "> quoted",
      "> twice",
    ].join("\n");
    const b = parseBlocks(md);
    expect(b.map((x) => x.t)).toEqual(["h", "p", "ul", "ol", "table", "code", "hr", "quote"]);
    expect(b[0]).toEqual({ t: "h", level: 1, text: "Title" });
    expect(b[1]).toEqual({ t: "p", text: "First line wraps here." });
    expect(b[2]).toEqual({ t: "ul", items: ["one continued", "two", "nested"] });
    expect(b[3]).toEqual({ t: "ol", items: ["third", "fourth"], start: 3 });
    expect(b[4]).toEqual({ t: "table", head: ["a", "b"], align: [null, "right"], rows: [["1", "`x|y`"], ["2"]] });
    expect(b[5]).toEqual({ t: "code", lang: "text", text: "| not a table |" });
    expect(b[7]).toEqual({ t: "quote", text: "quoted twice" });
  });

  it("ends a paragraph at a heading or a list without a blank line", () => {
    const b = parseBlocks("text\n## Next\nmore\n- item");
    expect(b.map((x) => x.t)).toEqual(["p", "h", "p", "ul"]);
  });

  it("survives an unclosed fence and Windows line ends", () => {
    const b = parseBlocks("a\r\n\r\n```\r\ncode");
    expect(b).toEqual([
      { t: "p", text: "a" },
      { t: "code", lang: "", text: "code" },
    ]);
  });
});

describe("parseInline", () => {
  it("reads bold, italics, code and links", () => {
    expect(parseInline("**Verdict: no.** See *this* `code` and [the study](results/x.md).")).toEqual([
      { t: "strong", c: [{ t: "text", v: "Verdict: no." }] },
      { t: "text", v: " See " },
      { t: "em", c: [{ t: "text", v: "this" }] },
      { t: "text", v: " " },
      { t: "code", v: "code" },
      { t: "text", v: " and " },
      { t: "link", href: "results/x.md", c: [{ t: "text", v: "the study" }] },
      { t: "text", v: "." },
    ]);
  });

  it("leaves snake_case names, lone stars and unclosed marks as text", () => {
    expect(plainText("tsmom_top20 and breakout_top10")).toBe("tsmom_top20 and breakout_top10");
    expect(plainText("2 * 3 = 6")).toBe("2 * 3 = 6");
    expect(plainText("**open")).toBe("**open");
    expect(plainText("a \\*literal\\* star")).toBe("a *literal* star");
  });

  it("nests marks", () => {
    expect(parseInline("**a *b* c**")).toEqual([
      { t: "strong", c: [{ t: "text", v: "a " }, { t: "em", c: [{ t: "text", v: "b" }] }, { t: "text", v: " c" }] },
    ]);
  });
});

describe("splitRow and studyLink", () => {
  it("keeps escaped bars and bars inside code", () => {
    expect(splitRow("| a \\| b | `c|d` | e |")).toEqual(["a | b", "`c|d`", "e"]);
  });

  it("names a study from its link", () => {
    expect(studyLink("results/breakout_study.md")).toBe("breakout_study");
    expect(studyLink("study:alpaca_universe")).toBe("alpaca_universe");
    expect(studyLink("https://example.com/x.md")).toBeNull();
    expect(studyLink("notes.txt")).toBeNull();
  });
});
