# Pythia CLI

Two programs:

- `pythia-server` is the engine without a window. It trades on paper unless you give it keys and arm it.
- `pythia` watches and steers a running engine from the terminal.

## Start

```bash
cp .env.example .env      # optional: keys, alerts; without keys everything stays on paper
./pythia serve            # starts pythia-server in this terminal, on 127.0.0.1:8787
```

In a second terminal:

```bash
./pythia status           # engine mode, kill switch, account, one line per autopilot
./pythia ls --all         # every autopilot, stopped ones too
./pythia show <id>        # one autopilot in detail
./pythia pause <id>
./pythia resume <id>
./pythia stop <id> --flatten
./pythia kill             # kill switch on or off, asks first
./pythia preflight        # what blocks a paper or live run
./pythia watch            # status every 10 seconds
```

`--json` prints the engine's raw answer, for scripts. Another engine is reached with `--url` or `PYTHIA_URL`, for example `PYTHIA_URL=http://127.0.0.1:8788 pythia status`.

On Windows the programs are `pythia.exe` and `pythia-server.exe`. On macOS, if the system refuses to run a downloaded binary, allow it once with `xattr -d com.apple.quarantine pythia pythia-server`.

Autopilots are started from the desktop app or the web UI, where you see what you are starting. Safety rules are in [SAFETY.md](https://github.com/SenseiIssei/Pythia/blob/main/SAFETY.md).
