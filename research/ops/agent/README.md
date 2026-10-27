# The agent folder

`run_agent.sh`, `Dockerfile`, `guard.py`, `research.md` and `care.md`: the research agent
on the server, see research/ops/README.md, "Research agent". The task lanes (research/ops/lanes,
"Task lanes") use this image, `guard.py`'s checks and its job rules (`table_problems(..., may_run=)`
with the task's list).

## mini_agent.py: a small coding agent for the local model (lane 5)

Lane 5 ran the Claude Code CLI against the owner's PC model (Qwen 27B through Ollama's
Anthropic-compatible API, 48k context, about 20 tokens a second). The CLI's own system
prompt and tool list take about 12,500 tokens of that. `mini_agent.py` does the same job
with a system prompt and tool list of about 1,100 tokens: plain Python 3, standard library
only, so it runs in the existing agent image without anything new.

    python /work/research/ops/agent/mini_agent.py --task /path/prompt.md [--rules /path/common.md]

The task file is the first user message; the house rules (`--rules` or `MINI_AGENT_RULES`,
e.g. common.md, at most 2,400 characters) go into the system prompt, built-in rules without
them (commit identity as configured, no em dash, no attribution, allowed files only, nothing
private, tests green before a commit).

| Environment | What | Default |
|---|---|---|
| `ANTHROPIC_BASE_URL` | the endpoint; the agent posts to `{base}/v1/messages`, non-streaming | api.anthropic.com |
| `ANTHROPIC_AUTH_TOKEN` | sent as `Authorization: Bearer`; never passed on to a command | (`ANTHROPIC_API_KEY`) |
| `ANTHROPIC_MODEL` | the model name, required | |
| `MINI_AGENT_CTX` | estimated history tokens before old tool results are summarised | 30000 |
| `MINI_AGENT_MAX_TURNS` | model calls at most (`--max-turns`) | 150 |
| `MINI_AGENT_WALL_S` | wall-clock limit in seconds | 10800 |
| `MINI_AGENT_MAX_TOKENS` | tokens a reply | 8192 |
| `MINI_AGENT_HTTP_TIMEOUT`, `MINI_AGENT_RUN_TIMEOUT` | seconds a model call, a command | 900, 900 |
| `MINI_AGENT_ROOT` | the clone (`--root`) | /work |
| `MINI_AGENT_OUT` | a second folder it may write, for the report | /out |
| `MINI_AGENT_READ_ROOTS` | more folders it may read, colon separated (e.g. /data) | none |

**Tools.** `list_files(glob)`, `read_file(path, start, lines)` (400 lines at most),
`grep(pattern, glob)` (80 matches at most), `graph(query, mode)` (`graphify explain` or
`affected` in the root when graphify-out exists), `write_file(path, content)`,
`replace(path, old, new)` (exact and unique, like an editor) and `run(cmd, cwd)`. Every
path is resolved (symlinks followed) and must stay inside the root (or `/out`); `.git` is
off limits; written text with an em dash is refused. `run` has no shell and allows only
`python -m pytest ...`, `python -m lab.<module>` of research/lab (not lab.pumpfun_rt) and
`git status|diff|add|commit` without options that write elsewhere, change the author or
skip hooks (`--output`, `--no-index`, `--author`, `--amend`, `--no-verify`, `-c`, `-C`, ...),
optionally behind `flock /run/lock/pythia/...`; a commit message with an em dash, a
Co-Authored-By line, Claude or AI is refused. Output is capped at 8,000 characters.

**Context.** Past `MINI_AGENT_CTX` old tool results become a one-line summary each (the
last test output and the last four messages stay whole) and old writes lose their bodies;
if that is not enough the oldest turns go and the task message gets a note with the plan
(the model's first text), the files changed and the last test output.

**Result.** One JSON line on stdout shaped like `claude -p --output-format json`: `type`,
`subtype` (success, error_max_turns, error_during_execution), `result` (the model's last
text), `num_turns`, `is_error`, `terminal_reason` (completed, max_turns, wall_clock,
api_error, setup), `duration_ms`, `usage`, `files_changed`. Exit 0 when the model ended
its turn, 1 otherwise. A line per turn and tool call goes to stderr.

Tests (a fake model server plays a session: read, replace, run the tests, commit; path
escapes, refused commands, the summarising step):

    python -m pytest -q research/ops/agent/test_mini_agent.py
