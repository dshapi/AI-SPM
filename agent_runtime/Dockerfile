# Agent runtime image — Phase 2 base + Phase 4.5 framework batteries.
#
# Replaces the Phase 1 stub. spm-api's agent_controller spawns one
# container from this image per customer-uploaded agent. The container
# runs `loader.py`, which imports aispm (populating connection
# constants from a DB-backed bootstrap call) and exec()s the customer's
# bind-mounted agent.py.
#
# Layer ordering is optimized for cache:
#   1. base image
#   2. SDK transport deps (aiokafka, httpx, pydantic) — change rarely
#   3. Framework batteries (langchain, llama_index) — heavier; pinned
#      so a customer's `from langchain.agents import ...` Just Works
#      out of the box without bringing their own image.
#   4. aispm package — changes per Phase 2 release
#   5. loader.py + entrypoint — last, fast to rebuild
#
# Customer's agent.py is bind-mounted at runtime; not COPYed here.

FROM python:3.12-slim

# Non-root user. The aispm-agents namespace enforces the Restricted
# PodSecurity profile, and the Pod spec sets runAsNonRoot=true; without
# a non-root USER here, kubelet refuses container start with
# CreateContainerConfigError ("container has runAsNonRoot and image
# will run as root, cannot validate user/uid").
#
# uid/gid 10001 — well above any system reserved range in python:3.12-slim.
# Match the runAsUser/runAsGroup numerics in agent_controller._build_pod
# so admission-time and runtime checks agree without consulting the image
# manifest.
RUN groupadd --system --gid 10001 agent \
 && useradd  --system --uid 10001 --gid agent \
             --home-dir /agent --shell /usr/sbin/nologin agent

WORKDIR /agent

# 2. SDK transport deps. Pinned major versions; concrete patch resolved
# at build time. Kept small to minimize image size and supply-chain
# surface; the framework batteries below are layered on top.
RUN pip install --no-cache-dir \
    aiokafka==0.11.* \
    httpx==0.27.*    \
    pydantic==2.*

# 3. Framework batteries — Phase 4.5 addition.
#
# Why bake these into the runtime image instead of letting customers
# ship their own?
#   - The five `Example agents/` reference frameworks (LangChain,
#     LlamaIndex). Without them the corresponding example crashes at
#     import. Baking them keeps "drop in the file → click Register"
#     truthful for every example.
#   - Each install adds ~80–120 MB; combined image is ~700 MB. Fine
#     for dev / single-tenant; production deploys that want a thinner
#     image can fork this Dockerfile and drop the line.
#   - Pin major versions so a customer's `from langchain.agents import
#     create_tool_calling_agent` doesn't break when langchain ships a
#     breaking 1.0. Patch versions float for security fixes.
RUN pip install --no-cache-dir \
    langchain==0.3.*         \
    langchain-openai==0.2.*  \
    "llama-index-core==0.11.*" \
    "llama-index-llms-openai-like==0.2.*"

# 4. aispm package
COPY agent_runtime/aispm /agent/aispm

# 5. Loader + entrypoint
COPY agent_runtime/loader.py /agent/loader.py

ENV PYTHONPATH=/agent

# Make /agent owned by the agent user. The customer's agent.py is
# mounted read-only from a per-agent ConfigMap (see agent_controller
# spawn_agent_pod); the loader imports + exec()s it.
RUN chown -R agent:agent /agent

USER 10001:10001

CMD ["python", "/agent/loader.py"]
