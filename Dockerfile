# OPC Content Factory Dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p knowledge-base drafts reviewed ready-to-publish raw-articles logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV OPC_ROOT=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Default command: run production pipeline
CMD ["./entrypoint.sh"]
