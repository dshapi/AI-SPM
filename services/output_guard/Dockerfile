FROM python:3.12-slim
WORKDIR /app
COPY services/output_guard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/output_guard/app.py .
CMD ["python", "app.py"]
