#!/bin/bash
set -e

echo "🚀 Initializing LiveOS Brain..."

# Wait for services to be ready
echo "⏳ Waiting for PostgreSQL..."
until PGPASSWORD=liveos_password psql -h postgres -U liveos -d liveos_brain -c '\q'; do
  sleep 1
done

echo "⏳ Waiting for MinIO..."
until curl -sf http://minio:9000/minio/health/live > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for Qdrant..."
until curl -sf http://qdrant:6333/health > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for Typesense..."
until curl -sf http://typesense:8108/health > /dev/null 2>&1; do
  sleep 1
done

echo "✅ All services ready!"

# Run initialization script
cd /app
python scripts/init_local.py

echo "🎉 LiveOS Brain is ready!"
