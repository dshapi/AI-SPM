FROM python:3.12-slim
WORKDIR /app
COPY services/threat-hunting-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/threat-hunting-agent/ .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8095", "--workers", "1"]
