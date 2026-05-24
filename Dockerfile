# ── Stage 1: Build Longfellow + prover/verifier ──────────────────────────────
FROM ubuntu:22.04 AS cpp-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git clang cmake make \
    libssl-dev libzstd-dev zlib1g-dev \
    libgtest-dev libbenchmark-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone Longfellow pinned to a specific commit for reproducible builds
RUN git clone https://github.com/google/longfellow-zk /longfellow-zk && \
    cd /longfellow-zk && git checkout c8495312046a447229a6a22b1dd4f0bcbf76d754

# Apply reviewer-namespace patch
COPY patches/add-reviewer-namespace.patch /tmp/patch.patch
RUN cd /longfellow-zk && git apply /tmp/patch.patch

# Build Longfellow Release
RUN cd /longfellow-zk && \
    CXX=clang++ cmake -DCMAKE_BUILD_TYPE=Release -S lib -B build && \
    cmake --build build -j$(nproc)

# Build prover_cli + verifier_cli
COPY prover/ /src/prover/
RUN cmake -DLONGFELLOW_ROOT=/longfellow-zk -S /src/prover -B /src/prover/build && \
    cmake --build /src/prover/build -j$(nproc)

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 libzstd1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Compiled binaries
COPY --from=cpp-builder /src/prover/build/prover_cli  ./prover/build/prover_cli
COPY --from=cpp-builder /src/prover/build/verifier_cli ./prover/build/verifier_cli
RUN chmod +x ./prover/build/prover_cli ./prover/build/verifier_cli

# Python dependencies
COPY issuer/requirements.txt ./issuer/requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r issuer/requirements.txt -r backend/requirements.txt

# Source
COPY issuer/ ./issuer/
COPY backend/ ./backend/

# Static assets (favicon, bot avatar, demo animation HTMLs)
COPY assets/ ./assets/

# Persistent data directory (mounted volume or /tmp fallback at runtime)
RUN mkdir -p /data

ENV PROVER_BIN=/app/prover/build/prover_cli
ENV VERIFIER_BIN=/app/prover/build/verifier_cli
ENV DB_PATH=/data/backend.db
ENV ISSUER_DB_PATH=/data/issuer.db
ENV PSEUDONYM_KEY_PATH=/data/.secrets/pseudonym-key.bin
ENV ISSUER_KEY_PATH=/data/issuer_key.pem

COPY scripts/start-service.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
