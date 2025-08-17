# Use Python 3.11 slim image for better security and smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for potential C extensions
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Expose the port the app runs on
EXPOSE 8000

# Health check - check if the process is running and port is listening
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import socket; sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(5); result = sock.connect_ex(('localhost', 8000)); sock.close(); exit(0 if result == 0 else 1)" || exit 1

# Run the application
CMD ["python", "observe_server.py"]