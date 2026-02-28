FROM python:3.12-slim

WORKDIR /app

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev libjpeg-dev libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY README.md README.md

WORKDIR /app/backend

# PORT is injected by Digital Ocean App Platform and AWS. Default 8000.
ARG PORT=8000
ENV PORT=${PORT}

EXPOSE ${PORT}

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-1}"
