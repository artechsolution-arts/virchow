FROM python:3.11.4-slim-bookworm

# 1. System Dependencies (OCR/PDF/Network)
# We need basic build tools and libraries for OCR/PDF manipulation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Dependency Installation
# Pre-install torch (CPU) to speed up builds and manage memory
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Project Source
# Copy the organized src folder and entry points
COPY . .

# 4. Environment Variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DOTS_OCR_USE_HF=true

# Default Port (API)
EXPOSE 8080

# Default command (overridden in compose for worker)
CMD ["python", "main.py"]
