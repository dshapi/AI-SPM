FROM python:3.12-slim
WORKDIR /app
COPY services/freeze_controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/freeze_controller/app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "2"]
