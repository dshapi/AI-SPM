FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/spm_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY spm/ ./spm/
COPY services/spm_api/app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092"]
