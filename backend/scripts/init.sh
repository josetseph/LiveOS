#!/bin/bash
set -e

echo "🚀 Initializing LiveOS Brain..."

# Wait for services to be ready
echo "⏳ Waiting for PostgreSQL..."
until PGPASSWORD=liveos_password psql -h postgres -U liveos -d liveos_brain -c '\q'; do
  sleep 1
done

echo "⏳ Waiting for Neo4j..."
until curl -f http://neo4j:7474 > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for MinIO..."
until curl -f http://minio:9000/minio/health/live > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for Qdrant..."
until curl -f http://qdrant:6333/health > /dev/null 2>&1; do
  sleep 1
done

echo "⏳ Waiting for Elasticsearch..."
until curl -f http://elasticsearch:9200 > /dev/null 2>&1; do
  sleep 1
done

echo "✅ All services ready!"

# Run initialization script
cd /app
python scripts/init_local.py

echo "🎉 LiveOS Brain is ready!"
