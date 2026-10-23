// One page on its own, for an iframe (`?page=<id>&embed=1`): no sidebar, no top
// bar, the page at the iframe's full width, and a small link to the whole app.

import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";

export function EmbedFrame({ href, children }: { href: string; children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col bg-canvas" data-embed="">
      <main className="pt-scroll min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-canvas" data-scroll-container="">
        <div className="flex justify-end px-4 pt-3 sm:px-8">
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline"
          >
            Open Pythia <ExternalLink size={13} aria-hidden />
          </a>
        </div>
        <div className="px-4 pb-12 pt-2 sm:px-8">{children}</div>
      </main>
    </div>
  );
}
