import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri-friendly Vite config (mirrors Odysync).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5174,
    strictPort: true,
    // Cargo's build output lives under the same root. Watching it crashes the
    // dev server with EBUSY on Windows whenever `npm run server` rebuilds and
    // holds a .pdb open.
    watch: { ignored: ["**/target/**", "**/src-tauri/target/**"] },
  },
  envPrefix: ["VITE_", "TAURI_"],
});
