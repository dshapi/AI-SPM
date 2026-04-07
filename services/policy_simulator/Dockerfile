FROM python:3.12-slim
WORKDIR /app
COPY services/policy_simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/policy_simulator/app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091", "--workers", "2"]
