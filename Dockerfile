FROM python:3.12-slim

WORKDIR /app

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev libjpeg-dev libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# PORT is injected by Digital Ocean App Platform and AWS. Default 8000.
ARG PORT=8000
ENV PORT=${PORT}

EXPOSE ${PORT}

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-1}"
