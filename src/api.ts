// The IPC seam. In the browser / web app, Pythia runs the TypeScript PaperEngine.
// Under the Tauri shell, the same UI talks to the Rust engine daemon through the
// TauriEngineClient. `getEngine()` returns whichever fits the current runtime;
// the store and pages never need to know which.
export { getEngine, isTauri } from "./engine";
export type { EngineClient, EngineState } from "./engine";
