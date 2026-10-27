---
# One lane task. Copy to /root/pythia-lanes/inbox/<id>.md, fill in, then queue it:
#   python3 /opt/pythia-ops/lanes/lanes.py queue-check <file> --repo /opt/pythia-agent/trusted
# (run_lane.sh does the same check again before it spends anything).
id: 125-example-study
title: Beispiel-Studie (X1)
# claude-opus-5-5, claude-sonnet-5-5 or claude-haiku-5-5; a held run gets one retry a step cheaper.
model: claude-sonnet-5-5
# The run is cut off at this cost (--max-budget-usd) and starts only if the budget left
# exceeds the reserve plus this. At most 30.
max_usd: 6
# Every file the run may change; whatever else it commits is dropped by the host.
# Globs: ** any folders, * and ? inside one name, {a,b} either. Never a path of the never list
# (lanes.py NEVER: real money and the lanes' own rules); the queue check refuses that.
allowed:
  - research/lab/lab/experiments/example_x1.py
  - research/lab/tests/test_example_x1.py
  - research/lab/results/example_x1*.md
  - research/lab/README.md
# What the run reads before anything else.
docs:
  - README.md
  - research/lab/README.md
# Commands from the repository root, plain chains of cd, python, pytest, npx, npm, cargo, bash.
tests:
  - cd research/lab && python -m pytest -q tests/test_example_x1.py
# retry: no       (optional: no second run when this one is held)
---
# X1: an example study

The brief. Paths are relative to research/lab/ unless they start with research/, docs/ or name a
file at the repository root. Every path of the Files line must be covered by `allowed` (the queue
check refuses the task otherwise); prose items such as "the new result file" are not checked.

Goal: ...
Steps:
- ...

Judged by: ...
Files: `lab/experiments/example_x1.py`, results/example_x1.md, research/lab/README.md, tests.
