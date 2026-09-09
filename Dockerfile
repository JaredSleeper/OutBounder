FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY . .

ENV PORT=8000
EXPOSE 8000

# Single worker: the enrichment queue runs in-process (rows are claimed with
# SKIP LOCKED so extra replicas are safe, but one is plenty for a draft).
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
