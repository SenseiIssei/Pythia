#!/usr/bin/env node
// Run a command with CC / CXX / CFLAGS / CXXFLAGS stripped from the environment.
//
// Why: on Windows these are often set machine-wide to a path containing a space
// (e.g. "C:\Program Files\..."). Rust's cc-rs splits the value on whitespace, so
// it tries to exec a tool literally named `C:\Program` and every native build
// (ring, and therefore anything using rustls) dies with:
//
//     failed to find tool "C:\Program": Das System kann die angegebene Datei nicht finden
//
// Clearing them for the child process only — your shell and the rest of your
// system are untouched.
import { spawn } from "node:child_process";

const [cmd, ...args] = process.argv.slice(2);
if (!cmd) {
  console.error("usage: node scripts/clean-env.mjs <command> [args...]");
  process.exit(2);
}

const env = { ...process.env };
for (const key of ["CC", "CXX", "CFLAGS", "CXXFLAGS"]) delete env[key];

// Pass one command string rather than (cmd, args[]) — with shell:true Node
// deprecates the array form (DEP0190). Quote only what needs it.
const quote = (a) => (/[\s"]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a);
const line = [cmd, ...args].map(quote).join(" ");

// shell:true so npm's node_modules/.bin shims (tauri) and cargo both resolve.
const child = spawn(line, { stdio: "inherit", env, shell: true });

child.on("error", (e) => {
  console.error(`failed to start "${cmd}": ${e.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
