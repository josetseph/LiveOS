#!/bin/bash
set -e

echo "🚀 Initializing LiveOS..."

# Wait for services to be ready
echo "⏳ Waiting for PostgreSQL..."
until PGPASSWORD=password psql -h postgres -U user -d liveos -c '\q'; do
  sleep 1
done

echo "⏳ Waiting for RustFS..."
until curl -sf http://rustfs:9000/health > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for Qdrant..."
until curl -sf http://qdrant:6333/ > /dev/null 2>&1; do
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

echo "🎉 LiveOS is ready!"
