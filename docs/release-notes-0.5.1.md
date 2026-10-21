# Pythia 0.5.1

Downloads for every platform, and a command line.

## Downloads

| Platform | File |
|---|---|
| Windows | `Pythia_0.5.1_x64-setup.exe` |
| macOS (Apple silicon and Intel) | `Pythia_0.5.1_universal.dmg` |
| Linux | `.AppImage`, `.deb` or `.rpm` |
| Command line | `pythia-cli-v0.5.1-<platform>` (`.zip` on Windows, `.tar.gz` elsewhere) |

The builds are not code-signed yet. Windows SmartScreen asks once: More info, then Run anyway. On macOS, right-click the app and choose Open the first time; for the command line, `xattr -d com.apple.quarantine pythia pythia-server`.

## Command line

The archive holds `pythia` and `pythia-server`, the engine without a window.

```bash
./pythia serve        # start the engine on 127.0.0.1:8787
./pythia status       # mode, kill switch, account, one line per autopilot
./pythia show <id>    # one autopilot in detail
./pythia pause <id> / resume <id> / stop <id> --flatten
./pythia kill         # kill switch, asks first
./pythia preflight    # what blocks a paper or live run
./pythia watch        # status every 10 seconds
```

`--json` gives the engine's raw answer for scripts, `--url` or `PYTHIA_URL` points at another engine. More in `cli/README.md`.

## Also

- Release builds run on GitHub Actions from the version tag (`.github/workflows/release.yml`).
- README in English, German, Chinese, Japanese, Korean, Spanish, French and Portuguese, with a plain architecture picture.
- The installer carries a publisher, category and description.

Nothing in this release trades real money unless you arm it. See SAFETY.md.
