"""
reset_storage.py — Delete all objects from the RustFS storage bucket.

Removes every stored file (attachments, audio, images, PDFs) without
deleting the bucket itself.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.utils.bucket_storage import s3_client


async def _reset_storage() -> None:
    async with await s3_client() as client:
        bucket = settings.BUCKET_NAME
        response = await client.list_objects_v2(Bucket=bucket)
        objects = response.get("Contents", [])
        if not objects:
            print("   ✅ RustFS bucket already empty.")
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


def reset_storage() -> None:
    print("🗑️  Resetting RustFS bucket...")
    asyncio.run(_reset_storage())
    print("✅ RustFS bucket reset complete.")


if __name__ == "__main__":
    reset_storage()
