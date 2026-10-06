FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2-binary's build fallback; harmless if unused.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# --reload + a bind-mounted source dir (see docker-compose.yml) means code
# changes on your host are picked up without rebuilding the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
