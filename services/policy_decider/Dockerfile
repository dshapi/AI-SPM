FROM python:3.12-slim
WORKDIR /app
COPY services/policy_decider/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/policy_decider/app.py .
CMD ["python", "app.py"]
