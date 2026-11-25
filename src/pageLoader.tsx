// A page's code is fetched when the page is first opened (or a moment after
// the start, so opening one later does not wait) and rendered at once when it
// is there already. React.lazy would show its fallback for 300 ms every time.

import { useEffect, useState, type ComponentType, type ReactNode } from "react";

export interface LoadedPage {
  /** Fetch the code; the same fetch for every caller until it fails. */
  load: () => Promise<ComponentType>;
  /** The component, once its code is here. */
  ready: () => ComponentType | null;
}

export function pageLoader(fetchPage: () => Promise<ComponentType>): LoadedPage {
  let page: ComponentType | null = null;
  let pending: Promise<ComponentType> | null = null;
  return {
    ready: () => page,
    load: () => {
      pending ??= fetchPage().then(
        (p) => (page = p),
        (e) => {
          pending = null; // the next open tries again
          throw e;
        },
      );
      return pending;
    },
  };
}

/** The page, or `fallback` while its code is on the way. A failed fetch goes to the error boundary. */
export function PageHost({ page, fallback }: { page: LoadedPage; fallback: ReactNode }) {
  const [, setArrived] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const Page = page.ready();
  useEffect(() => {
    if (page.ready()) return;
    let shown = true;
    page.load().then(
      () => shown && setArrived(true),
      (e: unknown) => shown && setError(e instanceof Error ? e : new Error(String(e))),
    );
    return () => {
      shown = false;
    };
  }, [page]);
  if (Page) return <Page />;
  if (error) throw error;
  return <>{fallback}</>;
}
