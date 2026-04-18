"""
reset_minio.py — Delete all objects from the MinIO storage bucket.

Removes every stored file (attachments, audio, images, PDFs) without
deleting the bucket itself.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.bucket_storage import s3_client
from app.core.config import settings


async def _reset_minio() -> None:
    async with await s3_client() as client:
        bucket = settings.BUCKET_NAME
        response = await client.list_objects_v2(Bucket=bucket)
        objects = response.get("Contents", [])
        if not objects:
            print("   ✅ MinIO bucket already empty.")
            return
        keys = [{"Key": obj["Key"]} for obj in objects]
        await client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
        print(f"   ✅ Deleted {len(keys)} object(s) from bucket '{bucket}'.")

        # Handle pagination (>1000 objects)
        while response.get("IsTruncated"):
            response = await client.list_objects_v2(
                Bucket=bucket,
                ContinuationToken=response["NextContinuationToken"],
            )
            objects = response.get("Contents", [])
            if objects:
                keys = [{"Key": obj["Key"]} for obj in objects]
                await client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
                print(f"   ✅ Deleted {len(keys)} more object(s).")


def reset_minio() -> None:
    print("🗑️  Resetting MinIO bucket...")
    asyncio.run(_reset_minio())
    print("✅ MinIO reset complete.")


if __name__ == "__main__":
    reset_minio()
