FROM python:3.12-slim
WORKDIR /app
COPY services/spm_mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/spm_mcp     /app/services/spm_mcp
COPY platform_shared      /app/platform_shared
COPY spm                  /app/spm
ENV PYTHONPATH=/app
EXPOSE 8500
CMD ["uvicorn","services.spm_mcp.main:app","--host","0.0.0.0","--port","8500"]
