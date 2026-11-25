import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PageHost, pageLoader } from "./pageLoader";

const Page = () => <h1>Risk</h1>;

describe("pageLoader", () => {
  it("fetches once, however many ask", async () => {
    const fetchPage = vi.fn(async () => Page);
    const p = pageLoader(fetchPage);
    expect(p.ready()).toBeNull();
    await Promise.all([p.load(), p.load()]);
    await p.load();
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(p.ready()).toBe(Page);
  });

  it("tries again after a failed fetch", async () => {
    const fetchPage = vi.fn(async () => Page).mockRejectedValueOnce(new Error("Failed to fetch dynamically imported module"));
    const p = pageLoader(fetchPage);
    await expect(p.load()).rejects.toThrow("Failed to fetch");
    expect(p.ready()).toBeNull();
    await p.load();
    expect(p.ready()).toBe(Page);
  });

  it("shows the fallback first and the page at once when its code is there", async () => {
    const p = pageLoader(async () => Page);
    expect(renderToStaticMarkup(<PageHost page={p} fallback="Loading" />)).toBe("Loading");
    await p.load();
    expect(renderToStaticMarkup(<PageHost page={p} fallback="Loading" />)).toBe("<h1>Risk</h1>");
  });
});
