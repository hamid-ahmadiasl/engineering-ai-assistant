FROM python:3.12-slim

WORKDIR /app

# PORT is intentionally unset. Render injects PORT at runtime; a Dockerfile
# ENV PORT would override it. Local Docker and Hugging Face leave PORT empty
# and the start command falls back to 7860.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEMO_MODE=true \
    EMBEDDING_PROVIDER=fastembed \
    EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    QUERY_TRANSLATION=both \
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
# The embedding model is not downloaded during the image build. fastembed loads
# it on first use, and the Render blueprint sets EMBEDDING_PROVIDER=hash so the
# free 512 MB instance never loads an ONNX model.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY eval ./eval
COPY README.md .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
