FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app

RUN addgroup --system claimtriage && adduser --system --ingroup claimtriage claimtriage

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY deploy ./deploy

RUN pip install --no-cache-dir .

USER claimtriage
EXPOSE 10000

CMD ["python", "scripts/start_hosted.py"]
