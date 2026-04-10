FROM python:3.12-slim
WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/api/app.py .
COPY services/api/ws/ ./ws/
COPY services/api/consumers/ ./consumers/
COPY services/api/models/ ./models/
COPY services/api/promptguard/ ./promptguard/
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
