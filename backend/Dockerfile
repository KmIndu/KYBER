FROM python:3.11-slim

WORKDIR /app

# System deps for building native wheels (if any)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY app/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/

# Create writable runtime data directory and give ownership to the app user
RUN mkdir -p /app/data /app/data/history && adduser --disabled-password --no-create-home appuser && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
