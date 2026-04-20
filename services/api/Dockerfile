FROM python:3.12-slim
WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/            ./platform_shared/
COPY services/api/app.py         .
COPY services/api/garak_runner.py .
COPY services/api/prompt_security/ ./prompt_security/
COPY services/api/promptguard/   ./promptguard/
COPY services/api/ws/            ./ws/
COPY services/api/consumers/     ./consumers/
COPY services/api/models/        ./models/
COPY services/api/routes/        ./routes/
# NOTE: single worker is REQUIRED.
# The WebSocket ConnectionManager and the simulation BackgroundTask share
# in-process state (the per-session queues and the pre-connect event buffer
# in ws/connection_manager.py). If uvicorn spawns multiple workers, the WS
# upgrade and the POST /simulate/single can be routed to DIFFERENT worker
# processes, so the BackgroundTask's _ws_emit broadcasts into a manager that
# has no subscribers for the session, and the browser (connected to a
# different worker) never sees a terminal event — stuck "running" forever.
# If horizontal scaling is needed, move transport to Kafka-only or add a
# Redis pub/sub bus so workers can fan out across processes.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
