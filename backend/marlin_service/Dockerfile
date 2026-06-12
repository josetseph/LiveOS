# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY marlin_service/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.10.0+cpu" "torchvision==0.25.0+cpu" && \
    pip install -r requirements.txt

COPY marlin_service/app.py .

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
