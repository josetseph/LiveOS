import sys
import os
import time
import asyncio
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_fixed

# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.core.database import engine
from app.services.graph import graph_service
from alembic.config import Config
from alembic import command


# 1. Wait for Postgres
@retry(stop=stop_after_attempt(10), wait=wait_fixed(2))
async def wait_for_postgres():
    print("⏳ Waiting for Local Postgres...")
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    print("✅ Postgres is Ready.")


# 2. Run Alembic Migrations
def run_migrations():
    print("🔄 Running Alembic Migrations...")
    try:
        # Load alembic.ini from backend root
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option(
            "sqlalchemy.url",
            settings.DATABASE_DIRECT_CONNECTION_URL.replace("+asyncpg", ""),
        )
        # Note: Alembic usually needs a sync driver (psycopg2) for migrations,
        # but our env.py handles async, so we might need to invoke it carefully.
        # Actually, running the command line `alembic upgrade head` is safer/easier than programmatic invocation with async.
        # Let's rely on subprocess.
        import subprocess

        # Get backend directory (parent of scripts/)
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        subprocess.run(["alembic", "upgrade", "head"], cwd=backend_dir, check=True)
        print("✅ Migrations Applied.")
    except Exception as e:
        print(f"❌ Migration Failed: {e}")
        sys.exit(1)


# 3. Init MinIO
@retry(stop=stop_after_attempt(10), wait=wait_fixed(2))
def init_minio():
    print("⏳ Check MinIO & Create Bucket...")
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.BUCKET_ACCESS_KEY_ID,
        aws_secret_access_key=settings.BUCKET_SECRET_ACCESS_KEY,
        region_name="us-east-1",
    )

    bucket_name = settings.BUCKET_NAME
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"✅ Bucket '{bucket_name}' already exists.")
    except ClientError:
        print(f"Creating bucket '{bucket_name}'...")
        s3.create_bucket(Bucket=bucket_name)
        print(f"✅ Bucket '{bucket_name}' created.")

    # Set Public Read Policy (Necessary for direct URL access in multimedia_service)
    import json

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
            }
        ],
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))
    print(f"✅ Public Read Policy applied to '{bucket_name}'.")


# 4. Init Neo4j
@retry(stop=stop_after_attempt(10), wait=wait_fixed(2))
def init_neo4j():
    print("⏳ Waiting for Neo4j & Initializing...")

    # Verify connection
    if not graph_service.verify_connection():
        raise Exception("Cannot connect to Neo4j")

    print("✅ Neo4j is Ready.")

    # Create constraints
    print("🔄 Creating Neo4j Constraints...")
    graph_service.execute_query(
        "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE"
    )
    graph_service.execute_query(
        "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE"
    )
    graph_service.execute_query(
        "CREATE CONSTRAINT concept_name_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE"
    )
    print("✅ Constraints created.")

    # Drop old vector index if exists
    print("🗑️  Cleaning up old vector index...")
    try:
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
    except Exception as e:
        print(f"   (No old index to drop: {e})")

    # Create vector index with configured dimensions
    print(f"🔄 Creating {settings.EMBEDDING_DIMENSIONS}-dim Vector Index...")
    try:
        query_index = f"""
        CREATE VECTOR INDEX note_vector_index IF NOT EXISTS
        FOR (n:Note)
        ON (n.embedding)
        OPTIONS {{indexConfig: {{
         `vector.dimensions`: {settings.EMBEDDING_DIMENSIONS},
         `vector.similarity_function`: 'cosine'
        }}}}
        """
        graph_service.execute_query(query_index)
        print(
            f"✅ Vector Index created with {settings.EMBEDDING_DIMENSIONS} dimensions."
        )
    except Exception as e:
        print(f"❌ Vector Index creation failed: {e}")
        raise


async def main():
    print("\n🚀 Initializing Local Infrastructure...\n")

    # Check Postgres
    await wait_for_postgres()

    # Run Migrations
    run_migrations()

    # Check MinIO
    init_minio()

    # Initialize Neo4j
    init_neo4j()

    print(
        "\n✨ Local Stack Initialized Successfully! You are fully offline-capable now.\n"
    )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
