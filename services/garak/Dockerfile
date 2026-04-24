# ── Stage 1: builder ─────────────────────────────────────────────────────────
# Rust + build-essential are needed to compile garak's native dep (base2048).
# They are NOT present in the final runtime image.
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --no-modify-path --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

COPY services/garak/requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:${PATH}"

# platform_shared is needed so main.py can call integration_config.hydrate_env_from_db()
COPY platform_shared/ ./platform_shared/
COPY services/garak/main.py .

# garak imports torch/transformers on startup — allow up to 90 s before health
# checks fire (controlled by start_period in docker-compose).
CMD ["/venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099"]
