// Window controls for the frameless native window. In the browser these are
// no-ops (the buttons still render but do nothing meaningful). Tauri's window
// API is imported lazily so the browser bundle never touches it.
import { isTauri } from "./engine";

async function win() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow();
}

export async function minimizeWindow(): Promise<void> {
  if (!isTauri()) return;
  (await win()).minimize();
}

// Close hides to the tray so the engine daemon keeps running in the background.
// The tray's Quit item is the real exit.
export async function hideWindow(): Promise<void> {
  if (!isTauri()) return;
  (await win()).hide();
}
