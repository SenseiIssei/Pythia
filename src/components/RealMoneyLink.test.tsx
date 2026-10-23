import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RealMoneyLink } from "./RealMoneyLink";

describe("RealMoneyLink", () => {
  it("points from the Autopilot page to the Real money page and counts what runs there", () => {
    const html = renderToStaticMarkup(<RealMoneyLink count={2} />);
    expect(html).toContain("Real money");
    expect(html).toContain("2 real-money autopilots running.");
    expect(renderToStaticMarkup(<RealMoneyLink count={0} />)).not.toContain("running");
  });
});
