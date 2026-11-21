FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860 \
    DEMO_MODE=true \
    EMBEDDING_PROVIDER=fastembed \
    EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 \
    FASTEMBED_CACHE_PATH=/app/models \
    LLM_PRESET=groq \
    LLM_PROVIDER=auto \
    DATA_DIR=/app/data \
    SEED_ON_STARTUP=true \
    ANONYMIZED_TELEMETRY=FALSE \
    CHROMA_TELEMETRY=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/models')"

COPY app ./app
COPY eval ./eval
COPY README.md .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
