FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libcairo2 libffi-dev libglib2.0-0 libfontconfig1 libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/spm_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY spm/ ./spm/
COPY services/spm_api/app.py .
COPY services/spm_api/integrations_routes.py .
COPY services/spm_api/integrations_seed_data.py .
COPY services/spm_api/connector_registry.py .
COPY services/spm_api/connector_probes.py .
# Phase 1 — agent runtime control plane modules. Flat-COPYed so the
# bare imports in app.py (`from agent_routes import router`) resolve
# at runtime the same way the existing model/integration modules do.
COPY services/spm_api/agent_routes.py .
COPY services/spm_api/agent_controller.py .
COPY services/spm_api/agent_validator.py .
# Phase 4 — chat pipeline + policy attachment.
COPY services/spm_api/agent_policies_routes.py .
COPY services/spm_api/agent_chat.py .
# Posture page backend — POST /posture/snapshots, /posture/summary used by
# the UI's Posture screen. Was missing from the image build until now,
# which is why the Posture page hit 404s in earlier debugging.
COPY services/spm_api/posture_routes.py .
# DB seed script — runs as the `db-seed` Job in the data-init phase.
# Creates the schema (Base.metadata.create_all) and inserts demo
# ModelRegistry + PostureSnapshot rows. Without this COPY the Job
# fails immediately with "can't open file '/app/seed_db.py'".
COPY services/spm_api/seed_db.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092"]
