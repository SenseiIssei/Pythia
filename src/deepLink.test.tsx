import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { openPythiaHref, pageQuery, readDeepLink, startScreen } from "./deepLink";
import { EmbedFrame } from "./components/EmbedFrame";
import { NAV } from "./nav";

describe("deep links", () => {
  it("opens the page the URL names", () => {
    expect(readDeepLink("?page=wallet")).toEqual({ page: "wallet", embed: false });
    expect(readDeepLink("?page=pumpfun")).toEqual({ page: "pumpfun", embed: false });
    expect(readDeepLink("?page=Wallet&embed=1")).toEqual({ page: "wallet", embed: true });
    for (const n of NAV) expect(readDeepLink(pageQuery(n.id)).page).toBe(n.id);
  });

  it("follows redirects and ignores what is not a page", () => {
    expect(readDeepLink("?page=practice").page).toBe("autopilot");
    expect(readDeepLink("?page=../etc")).toEqual({ page: null, embed: false });
    expect(readDeepLink("")).toEqual({ page: null, embed: false });
    expect(readDeepLink("?embed=1")).toEqual({ page: null, embed: false });       // nothing to embed
    expect(readDeepLink("?page=wallet&embed=0").embed).toBe(false);
    expect(readDeepLink("?page=wallet&embed=true").embed).toBe(true);
  });

  it("builds the query and the way back to the whole app", () => {
    expect(pageQuery("wallet", true)).toBe("?page=wallet&embed=1");
    expect(openPythiaHref({ pathname: "/pythia/", search: "?page=wallet&embed=1" })).toBe("/pythia/?page=wallet");
    expect(openPythiaHref({ pathname: "/", search: "?embed=1" })).toBe("/");
  });
});

describe("the embed mode", () => {
  it("shows the legal notice until it was accepted once, then the page alone, never the tour", () => {
    expect(startScreen({ accepted: false, onboarded: false, embed: true })).toBe("legal");
    expect(startScreen({ accepted: true, onboarded: false, embed: true })).toBe("embed");
    expect(startScreen({ accepted: true, onboarded: true, embed: true })).toBe("embed");
    expect(startScreen({ accepted: true, onboarded: false, embed: false })).toBe("onboarding");
    expect(startScreen({ accepted: true, onboarded: true, embed: false })).toBe("app");
  });

  it("frames one page with a small Open Pythia link and nothing else", () => {
    const html = renderToStaticMarkup(
      <EmbedFrame href="/?page=wallet">
        <p>the wallet page</p>
      </EmbedFrame>,
    );
    expect(html).toContain("the wallet page");
    expect(html).toContain("Open Pythia");
    expect(html).toContain('href="/?page=wallet"');
    expect(html).toContain('target="_blank"');
    expect(html).not.toContain('aria-label="Pages"');           // no sidebar
    expect(html).not.toContain("Pythia</span>");                  // no top bar brand
  });
});
