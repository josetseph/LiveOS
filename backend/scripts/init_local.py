import sys
import os
import asyncio
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_fixed

# Add parent dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Add scripts dir so per-service init modules are importable
_scripts_dir = os.path.abspath(os.path.dirname(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from app.core.config import settings
from app.core.database import engine
from alembic.config import Config

from init_neo4j import init_neo4j
from init_qdrant import init_qdrant
from init_elasticsearch import init_elasticsearch


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


async def main():
    print("\n🚀 Initializing Local Infrastructure...\n")

    # Check Postgres
    await wait_for_postgres()

    # Run Migrations
    run_migrations()

    # Check MinIO
    init_minio()

    # Initialize Qdrant
    init_qdrant()

    # Initialize Elasticsearch
    init_elasticsearch()

    # Initialize Neo4j
    init_neo4j()

    print(
        "\n✨ Local Stack Initialized Successfully! You are fully offline-capable now.\n"
    )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
