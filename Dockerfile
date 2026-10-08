FROM python:3.11-slim

# Avoid writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies including Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY data/ ./data/
COPY eval/ ./eval/

# Install the application and dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[pipeline]"

# Expose FastAPI default port
EXPOSE 8000

# Run the FastAPI server locally
CMD ["uvicorn", "co_extract.api:app", "--host", "0.0.0.0", "--port", "8000"]
