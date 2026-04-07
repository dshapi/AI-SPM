FROM python:3.11-slim
WORKDIR /app
COPY services/spm_aggregator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY spm/ ./spm/
COPY services/spm_aggregator/app.py .
CMD ["python", "app.py"]
