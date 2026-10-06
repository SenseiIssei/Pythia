# The standalone backend, for running Pythia headless (on the VPS: model
# shadow scoring around the clock, paper engine, no keys).
#
#   docker build -f server/Dockerfile -t pythia-server .
#   docker run -d --name pythia-server -p 127.0.0.1:8787:8787 \
#     -e PYTHIA_MODELS=/models -v /srv/pythia-data/models:/models pythia-server
#
# The API has no authentication. Publish it on 127.0.0.1 only, never on a
# public interface.
FROM rust:1-slim-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libdbus-1-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cargo build --release -p pythia-server

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libdbus-1-3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/target/release/pythia-server /usr/local/bin/pythia-server
COPY --from=build /src/config /app/config
WORKDIR /app
ENV PYTHIA_BIND=0.0.0.0:8787
EXPOSE 8787
CMD ["pythia-server"]
