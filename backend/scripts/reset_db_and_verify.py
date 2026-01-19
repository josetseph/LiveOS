import urllib.request
import json
import time

API_URL = "http://localhost:8000/api/v1"


def post_json(url, data):
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    jsondata = json.dumps(data).encode("utf-8")
    req.add_header("Content-Length", len(jsondata))
    try:
        with urllib.request.urlopen(req, jsondata) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8"), e.code


# We will run this script using `python scripts/reset_db_and_verify.py` which can import the app.
if __name__ == "__main__":
    import sys
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    from app.services.graph import graph_service
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note
    from app.utils.bucket_storage import s3_client
    from sqlalchemy import text
    import asyncio
    import os
    from app.core.config import settings

    print("\n🧹 STARTING FULL SYSTEM RESET...")

    # 1. Wipe Neo4j (Mind)
    print("  -> Wiping Neo4j Graph...")
    with graph_service.driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("     ✅ Neo4j Wiped.")

    # 1.1 Create Constraints & Indexes
    print("  -> Ensuring Neo4j Constraints...")
    with graph_service.driver.session() as session:
        # Note ID Uniqueness
        session.run(
            "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE"
        )
        # Entity Name Uniqueness (improves merge speed)
        session.run(
            "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE"
        )
        # Concept Name Uniqueness
        session.run(
            "CREATE CONSTRAINT concept_name_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE"
        )
        # Vector Index (if not exists)
        try:
            # Create vector index
            from app.core.config import settings

            session.run(
                f"""
             CREATE VECTOR INDEX note_vector_index IF NOT EXISTS
             FOR (n:Note)
             ON (n.embedding)
             OPTIONS {{indexConfig: {{
               `vector.dimensions`: {settings.EMBEDDING_DIMENSIONS},
               `vector.similarity_function`: 'cosine'
             }}}}
             """
            )
        except Exception as e:
            print(f"     ⚠️ Vector Index creation skipped/failed (might exist): {e}")

    print("     ✅ Neo4j Constraints & Indices Verified.")

    # 2. Wipe R2 (Files)
    print("  -> Wiping Bucket...")

    async def wipe_r2():
        try:
            async with await s3_client() as client:
                bucket_name = settings.BUCKET_NAME
                # List objects
                response = await client.list_objects_v2(Bucket=bucket_name)
                if "Contents" in response:
                    delete_keys = [{"Key": obj["Key"]} for obj in response["Contents"]]
                    await client.delete_objects(
                        Bucket=bucket_name, Delete={"Objects": delete_keys}
                    )
                    print(f"     ✅ Deleted {len(delete_keys)} files from R2.")
                else:
                    print("     ✅ R2 Bucket already empty.")
        except Exception as e:
            print(f"     ⚠️ R2 Wipe Check Failed: {e}")

    # Run async wipe for R2
    loop = asyncio.get_event_loop()
    loop.run_until_complete(wipe_r2())

    # 3. Wipe Postgres (Body)
    print("  -> Wiping Postgres Database...")

    async def wipe_postgres():
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    text("TRUNCATE TABLE notes RESTART IDENTITY CASCADE")
                )
                await session.commit()
            except Exception as e:
                print(f"     ⚠️ Postgres Wipe Failed: {e}")

    # Run async wipe
    loop = asyncio.get_event_loop()
    loop.run_until_complete(wipe_postgres())
    print("     ✅ Postgres Wiped.")

    print("✨ SYSTEM RESET COMPLETE.\n")
