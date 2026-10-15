// The lab's write-ups as they were in the repository when the app was built.
// Each file is its own small chunk, loaded when the Research page asks for it;
// the engine serves newer copies (GET /api/lab/studies) that replace these.

const files = import.meta.glob<string>("../research/lab/results/*.md", { query: "?raw", import: "default" });

/** research/lab/README.md, for its "Results so far" table. */
export async function labReadme(): Promise<string> {
  return (await import("../research/lab/README.md?raw")).default;
}

/** Every bundled write-up, by name (the file name without .md). */
export async function bundledStudies(): Promise<Record<string, string>> {
  const entries = await Promise.all(
    Object.entries(files).map(async ([path, load]) => {
      const name = path.split("/").pop()!.replace(/\.md$/, "");
      try {
        return [name, await load()] as const;
      } catch {
        return [name, ""] as const;
      }
    }),
  );
  return Object.fromEntries(entries.filter(([, md]) => md));
}
