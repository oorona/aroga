FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash agora

# Ensure /app is owned by agora user and no logs directory exists
RUN chown -R agora:agora /app && \
    rm -rf /app/logs && \
    rm -f /app/*.log

USER agora

# Expose health check port (if needed later)
EXPOSE 8080

# Health check command
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import asyncio; from cogs.core import CoreCog; exit(0)" || exit 1

# Run the debug script instead of the main bot
# Debug: Show what's in the container
RUN echo "=== Container contents ===" && \
    ls -la /app && \
    echo "=== Checking for logs ===" && \
    find /app -name "*log*" -o -name "logs" 2>/dev/null || echo "No logs found"

# Start the bot
CMD ["python", "main.py"]