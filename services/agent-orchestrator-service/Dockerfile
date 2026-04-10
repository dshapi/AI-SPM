# ─────────────────────────────────────────────────────────────────────────────
# agent-orchestrator-service  —  Dockerfile
# Multi-stage build: keeps the final image lean (~120 MB).
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools for packages with C extensions (cryptography, uvloop)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/agent-orchestrator-service/requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="agent-orchestrator-service"
LABEL org.opencontainers.image.version="1.0.0"

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Create data directory with correct ownership before switching users
RUN mkdir -p /data && chown appuser:appgroup /data

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy shared platform library
COPY --chown=appuser:appgroup platform_shared/ ./platform_shared/

# Copy application source
COPY --chown=appuser:appgroup services/agent-orchestrator-service/ .

USER appuser

# Expose service port
EXPOSE 8094

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8094/health')"

# Entry point
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8094", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log"]
