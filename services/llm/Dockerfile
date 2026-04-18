FROM python:3.12-slim

# Build tools needed to compile llama-cpp-python from source
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake curl && \
    rm -rf /var/lib/apt/lists/*

# llama-cpp-python[server] bundles an OpenAI-compatible HTTP server
# CMAKE_ARGS controls the backend; empty = CPU-only (works everywhere)
RUN CMAKE_ARGS="-DGGML_NATIVE=OFF" \
    pip install --no-cache-dir "llama-cpp-python[server]>=0.3.2"

EXPOSE 8080

# All config is passed via CMD args in docker-compose
ENTRYPOINT ["python", "-m", "llama_cpp.server"]
