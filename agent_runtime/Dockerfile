# Agent runtime image — Phase 2.
#
# Replaces the Phase 1 stub. spm-api's agent_controller spawns one
# container from this image per customer-uploaded agent. The container
# runs `loader.py`, which imports aispm (populating connection
# constants from env) and exec()s the customer's bind-mounted agent.py.
#
# Layer ordering is optimized for cache:
#   1. base image
#   2. SDK runtime deps (aiokafka, httpx, mcp, pydantic) — change rarely
#   3. aispm package — changes per Phase 2 release
#   4. loader.py + entrypoint — last, fast to rebuild
#
# Customer's agent.py is bind-mounted at runtime; not COPYed here.

FROM python:3.12-slim
WORKDIR /agent

# 2. SDK runtime deps. Pinned major versions; concrete patch resolved
# at build time. Phase 2 keeps the dep list small to minimize image size
# and supply-chain surface.
RUN pip install --no-cache-dir \
    aiokafka==0.11.* \
    httpx==0.27.*    \
    pydantic==2.*

# 3. aispm package
COPY agent_runtime/aispm /agent/aispm

# 4. Loader + entrypoint
COPY agent_runtime/loader.py /agent/loader.py

ENV PYTHONPATH=/agent

# spawn_agent_container bind-mounts the customer's agent.py to
# /agent/agent.py at runtime; the loader imports + exec()s it.
CMD ["python", "/agent/loader.py"]
