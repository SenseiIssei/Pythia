#!/usr/bin/env bash
# The lab's local language model (B4): llama.cpp's server with Qwen3 4B Instruct (GGUF Q4_K_M), container
# pythia-local-llm, on 127.0.0.1:8091 only. It words the briefing's summary line, the lab card's top line and tags
# the news (lab.ai.local); it decides nothing, never touches trading and never sees a key.
#
#   sudo /opt/pythia-ops/local-llm.sh [up|down|status|bench] [--models DIR] [--port N]
#
#   up      (the default; job local-llm every 15 minutes) download the model once if it is missing (pinned file
#           and sha256, into --models, /srv/pythia-llm, outside the data store so no sync or backup carries it),
#           start the container when it is not running or its settings changed; nothing when it runs as it should
#   down    stop and remove the container (the jobs fall back to the owner's PC or to their templates)
#   status  running or not, its memory now
#   bench   one short call, the tokens a second it measured
#
# Before a start, up checks that nothing else holds the port (8091; --port only for tests) and names what does;
# when docker run fails, its own error goes to the log and the job's exit code, never to /dev/null.
#
# Kept up rather than started per job: the jobs run in containers without docker, an idle server takes no CPU and
# about 0.7 GB of its own memory (the 2.4 GB model file is mapped and the kernel may drop it), a cold start takes
# a few seconds. Limits: 3 CPUs at a low CPU share (256, other services first), 4 GB memory, no swap beyond it,
# read-only, no capabilities, the model folder read only. --no-repack keeps the weights in the mapped file
# (with repacking it held a second copy, 4.8 GB). Measured on the VPS with 3 threads: about 50 to 60 tokens a
# second in, 15 to 19 out, 3.2 GB at most.
set -euo pipefail

models=/srv/pythia-llm
cmd=up
name=pythia-local-llm
port=8091
image="ghcr.io/ggml-org/llama.cpp:server@sha256:5741ab30aae42af23ca57d9b98a6d4544cb09c21f372f92c5ee55312fa8b8b0c"
repo=unsloth/Qwen3-4B-Instruct-2507-GGUF
rev=a06e946bb6b655725eafa393f4a9745d460374c9
file=Qwen3-4B-Instruct-2507-Q4_K_M.gguf
sha=3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597
while [ $# -gt 0 ]; do
  case $1 in
    up|down|status|bench) cmd=$1 ;;
    --models) models=${2:?--models needs a folder}; shift ;;
    --port) port=${2:?--port needs a number}; shift ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "local-llm: $*" >&2; exit 1; }
command -v docker >/dev/null || die "docker is not installed"
# What the running container must match; a change here recreates it.
args=(-m "/models/$file" --host 0.0.0.0 --port 8080 --alias qwen3-4b-instruct -t 3 -c 4096 --parallel 1
      --no-repack --cache-ram 0)
want="$image $sha ${args[*]}"

running() { [ "$(docker container inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" = true ]; }

case $cmd in
  down)
    docker rm -f "$name" >/dev/null 2>&1 || true
    echo "local-llm: $name removed"
    exit 0 ;;
  status)
    if running; then
      echo "local-llm: running, $(docker stats --no-stream --format '{{.MemUsage}}' "$name")"
    else
      echo "local-llm: not running"
    fi
    exit 0 ;;
  bench)
    running || die "not running (local-llm.sh up)"
    out=$(curl -s -m 120 -H 'Content-Type: application/json' "http://127.0.0.1:$port/v1/chat/completions" \
      -d '{"messages":[{"role":"user","content":"Write two short sentences about a quiet market day."}],"max_tokens":64}')
    echo "$out" | python3 -c 'import json,sys; t=json.load(sys.stdin).get("timings") or {}; print("local-llm: %s tokens in at %.1f/s, %s out at %.1f/s" % (t.get("prompt_n"), t.get("prompt_per_second") or 0, t.get("predicted_n"), t.get("predicted_per_second") or 0))'
    echo "local-llm: $(docker stats --no-stream --format '{{.MemUsage}}' "$name")"
    exit 0 ;;
esac

[ "$(id -u)" -eq 0 ] || die "run it as root (docker, $models)"
install -d -m 755 "$models"
if [ ! -f "$models/$file" ]; then
  echo "local-llm: downloading $file (about 2.5 GB)"
  tmp="$models/.$file.part"
  curl -fsSL --retry 3 -o "$tmp" "https://huggingface.co/$repo/resolve/$rev/$file" || { rm -f "$tmp"; die "download failed"; }
  echo "$sha  $tmp" | sha256sum -c --quiet - || { rm -f "$tmp"; die "sha256 of $file does not match, removed"; }
  chmod 644 "$tmp"
  mv "$tmp" "$models/$file"
fi

if running && [ "$(docker container inspect -f '{{index .Config.Labels "pythia.llm"}}' "$name")" = "$want" ]; then
  exit 0
fi
docker rm -f "$name" >/dev/null 2>&1 || true
# Something else on the port makes docker run fail with 125 (and answers the jobs' calls with its own errors).
if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
  holder=$(command -v ss >/dev/null && ss -Hltnp "sport = :$port" 2>/dev/null | tr -s ' ' | head -n 3 || true)
  die "port $port on 127.0.0.1 is taken by another program, $name not started${holder:+: $holder}"
fi
rc=0
err=$(docker run -d --name "$name" --restart unless-stopped --label "pythia.llm=$want" \
  --cpus 3 --cpu-shares 256 --memory 4g --memory-swap 4g \
  -p "127.0.0.1:$port:8080" -v "$models:/models:ro" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --log-opt max-size=10m --log-opt max-file=3 \
  "$image" "${args[@]}" 2>&1 >/dev/null) || rc=$?
[ "$rc" -eq 0 ] || { echo "local-llm: docker run failed (exit $rc): $err" >&2; exit "$rc"; }
for _ in $(seq 1 60); do
  curl -s -m 2 "http://127.0.0.1:$port/health" | grep -q '"ok"' && { echo "local-llm: $name up on 127.0.0.1:$port"; exit 0; }
  sleep 2
done
docker logs --tail 20 "$name" >&2 || true
die "$name started but does not answer on 127.0.0.1:$port (docker logs $name)"
