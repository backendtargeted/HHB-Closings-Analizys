FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY app/ ./app/

# Create directories for uploads and exports
RUN mkdir -p uploads exports reports

# Expose port
EXPOSE 8000

# Run with Gunicorn
# Large multipart uploads can take longer than the default 30s timeout.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "--timeout", "600", "--graceful-timeout", "120", "app.main:app"]
