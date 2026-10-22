# The research agent's image: the lab image (Python and every lab dependency) plus
# Node, Claude Code, git and ssh, so the agent can read the code, run studies
# against /data and push a branch. Built by run_agent.sh on the server:
#
#   docker build -t pythia-agent -f /opt/pythia-ops/agent/Dockerfile /opt/pythia-ops/agent
#
# It never gets the Docker socket, /etc/pythia or the wallet; run_agent.sh mounts
# only the agent's own clone, the data folder, the job locks and a deploy key.
ARG BASE=pythia-lab
FROM node:24-slim AS node
FROM ${BASE}

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates util-linux procps curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --no-fund --no-audit @anthropic-ai/claude-code \
 && pip install --no-cache-dir pytest

ENV DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 IS_SANDBOX=1 PYTHIA_DATA=/data
WORKDIR /work
