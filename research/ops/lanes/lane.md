You implement one task in Pythia (public repo SenseiIssei/Pythia), a paper-first trading system
with a small real-money pump.fun bot. You run on the lab server in a container. /work is a fresh
clone on main: commit your work on main there (you cannot push; the host checks your commits and
lands them only when its checks pass). /data is the lab's data folder, READ ONLY. Write scratch
output under /out. Your home folder is empty and gone after the run. For anything that loads big
panels: `flock /run/lock/pythia/heavy.lock ...` and stay under 6 GB memory.
Trials go into R5's registry through `lab.metrics.register` as usual: in this container it
writes into a copy, /out/trials/registry.jsonl (PYTHIA_TRIALS_REGISTRY, seeded with the server's
lines), because /data is read only. The host appends the copy's new ids to the server's registry
after every run, held or landed (a stopped study looked at the data too): leave that file in place
and never edit or remove its lines.

The files you may change are listed below under "Allowed". The host DROPS every file outside that
list (and says so to the owner); do not edit a README, a doc or a job table the list does not name,
even if earlier commits did. What the owner should know goes into your report instead. A path on
the never list (real money, the lanes' and the agent's own rules) is dropped whatever happens.

Before every commit run the host's own check, from the base the host compares against:

    python3 /lane/research/ops/lanes/lanes.py check --task /lane/task.md --repo /work --tests

It prints HOLD (fix it, or the whole run is refused), DROPPED (undo those files) and WARN lines,
and "ok" when the host would take the run as it is. It covers the allow list, the never list, an
em dash anywhere (code, docs, commit messages), private lines (addresses, keys, personal paths),
binary or over 1 MB files, live-data names, attribution lines, the job table rules and the task's
tests. Commit until it says ok.

Hard rules:
- Never weaken a safety check, cap, gate, kill switch, ack rule or test of the live bots. Never
  read or print a key, never add code that moves money out of a wallet, never import the live
  modules (live_exec, live_gate, txbuild, wallet, ...) from lab code: copy a constant instead.
- Public repository: no IP addresses, host names, e-mail addresses, wallet addresses, keys, tokens,
  webhook URLs or personal paths in files or commit messages.
- Never use the em dash character anywhere. Test fixtures are text (JSON, CSV) or built in the test.
- Commit messages: a subject under 200 characters, the detail in the body, no Co-Authored-By, no
  mention of Claude or AI.
- Follow the style of the code you change (dense, plain comments, no refactoring the task does not
  need). Everything you touch keeps its tests green and gets new tests.
- Finish with a German report of at most 15 short lines in /out/report.md: what changed, what the
  owner sees now, what the owner must do (if anything), the tests run.
