import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { LabFactory } from "./LabFactory";
import { FACTORY } from "../labFactory.fixture";

describe("LabFactory panel", () => {
  it("shows both factories, the books in EUR, the zoo's picks and the allocator's posterior", () => {
    const html = renderToStaticMarkup(<LabFactory data={FACTORY} err="" now={FACTORY.factories!.F3!.updated_ms! + 3_600_000} />);
    expect(html).toContain("Forschungs-Fabrik");
    expect(html).toContain('data-factory="F3"');
    expect(html).toContain('data-factory="F2"');
    expect(html).toContain("330 trials");
    expect(html).toContain("Sharpe 0.123");
    expect(html).toContain("F3_00042");
    expect(html).toContain("-0.031 SOL");
    expect(html).toContain('data-book="F3_00011"');
    expect(html).toContain("€97.60");
    expect(html).toContain("€80.00");
    expect(html).toContain("win30");
    expect(html).toContain("no report yet");
    expect(html).toContain("would pick P_pool5_top30t");
    expect(html).toContain("the live bot keeps P_pool0_wait");
    expect(html).toContain('data-arm="P_pool0_wait_lock"');
    expect(html).toContain("62 %");
    expect(html).toContain("+1.23 %");
  });

  it("says why when there is nothing to show", () => {
    expect(renderToStaticMarkup(<LabFactory data={null} err="The research factory is read by the connected server." now={0} />)).toContain("connected server");
    expect(renderToStaticMarkup(<LabFactory data={{ found: false }} err="" now={0} />)).toContain("No factory, zoo or allocator report");
  });
});
