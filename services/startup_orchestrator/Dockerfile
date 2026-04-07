FROM python:3.12-slim
WORKDIR /app
COPY services/startup_orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/startup_orchestrator/app.py .
CMD ["python", "app.py"]
