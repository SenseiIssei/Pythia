# The research agent's image: the lab image (Python and every lab dependency) plus
# Node, Claude Code and git, so the agent can read the code, run studies against
# /data and commit in its own clone. Built by run_agent.sh on the server:
#
#   docker build -t pythia-agent -f /opt/pythia-ops/agent/Dockerfile /opt/pythia-ops/agent
#
# run_agent.sh starts it as the unprivileged user "agent" (uid 10001) with every
# capability dropped, no-new-privileges, its own Docker network and a fresh empty
# home (tmpfs) on every run. It mounts only the agent's clone (/work), the data
# folder READ ONLY (/data), the agent's one output folder (/out), the job locks
# read only, the director's drafts read only and the host snapshot read only. It
# never gets the Docker socket, a git key, /etc/pythia, the wallet or its files,
# /opt/pythia-live or the secrets in /root/pythia-agent-secrets (only the Claude
# API key, as an environment variable). What it needs from the network: the Claude
# API (api.anthropic.com); github.com and raw.githubusercontent.com to read public
# docs such as pump.fun's IDLs; nothing else (packages are baked in here).
ARG BASE=pythia-lab
FROM node:24-slim AS node
FROM ${BASE}

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates util-linux procps curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --no-fund --no-audit @anthropic-ai/claude-code \
 && pip install --no-cache-dir pytest \
 && useradd --uid 10001 --user-group --create-home --home-dir /home/agent --shell /bin/bash agent

ENV DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 IS_SANDBOX=1 PYTHIA_DATA=/data
USER agent
WORKDIR /work
