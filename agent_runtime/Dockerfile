# agent-runtime base image — Phase 1 stub.
#
# spm-api's agent_controller.spawn_agent_container() spawns a container
# from this image for every customer agent. Phase 1's stub just prints
# the env vars the controller injected and stays alive long enough for
# orchestration tests to verify "running" state. Phase 2 replaces this
# with the real `aispm` SDK package + agent loader that imports the
# customer's bind-mounted /agent/agent.py and runs main().
#
# The customer's agent.py is bind-mounted onto /agent/agent.py at runtime
# (see spawn_agent_container's `volumes` arg). Phase 1 ignores it and
# runs the stub.

FROM python:3.12-slim
WORKDIR /agent

# Pre-install nothing in Phase 1 — stub is stdlib-only. Phase 2 will:
#   COPY agent_runtime/aispm /agent/aispm
#   RUN  pip install kafka-python-ng httpx mcp pydantic
COPY agent_runtime/stub_main.py /agent/stub_main.py

# /agent/agent.py is bind-mounted at runtime; do NOT COPY it here.
CMD ["python", "/agent/stub_main.py"]
