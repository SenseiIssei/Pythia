import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PumpfunLab } from "./PumpfunLab";
import { LAB } from "../pumpfunLab.fixture";
import type { StudyView } from "../researchView";

const study: StudyView = {
  id: "pumpfun_exits_y8",
  title: "P_pool0: a -10 % stop, a sell-pressure exit, waiting for the pool (Y8)",
  code: "pumpfun_exits_y8",
  verdict: "No variant beats P_pool0.",
  kind: "ruled_out",
  date: "2026-10-23",
  file: "pumpfun_exits_y8",
  group: "study",
};

describe("PumpfunLab section", () => {
  it("shows the verdict, the execution, a row and a chart per strategy and the newest studies", () => {
    const html = renderToStaticMarkup(<PumpfunLab lab={LAB} studies={[study]} err="" now={LAB.updatedMs! + 3_600_000} />);
    expect(html).toContain("pump.fun lab");
    expect(html).toContain("Paper only. 4 day(s) of record.");
    expect(html).toContain("33 live buys landed");
    expect(html).toContain("9074 ms");
    for (const r of ["P_press10", "P_pool0", "P_new", "P_snipe_dev"]) expect(html).toContain(`data-strategy="${r}"`);
    // One small chart per strategy (an empty one waits for points).
    expect(html.match(/role="img"/g)?.length).toBeGreaterThanOrEqual(4);
    expect(html).toContain("+30.0 %");
    expect(html).toContain("No variant beats P_pool0.");
    expect(html).toContain("results/pumpfun_exits_y8.md");
  });

  it("says why when there is nothing to show", () => {
    expect(renderToStaticMarkup(<PumpfunLab lab={null} studies={[]} err="The pump.fun lab is read by the connected server." now={0} />)).toContain("connected server");
    expect(renderToStaticMarkup(<PumpfunLab lab={{ ...LAB, found: false }} studies={[]} err="" now={0} />)).toContain("No pump.fun study report");
  });
});
