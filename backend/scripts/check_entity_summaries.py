#!/usr/bin/env python3
"""Check entity summary status in Neo4j."""

from neo4j import GraphDatabase
import os

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")),
)

with driver.session() as session:
    # Check total entities
    result = session.run("MATCH (e:Entity) RETURN count(e) as count")
    total = result.single()["count"]

    # Check entities with 'None yet.' or empty summary
    result2 = session.run(
        """
        MATCH (e:Entity)
        WHERE e.summary IS NULL OR e.summary = '' OR e.summary = 'None yet.' OR e.summary CONTAINS 'None yet'
        RETURN count(e) as count
    """
    )
    none_yet = result2.single()["count"]

    # Check entities with real summaries
    with_summary = total - none_yet

    print(f"Total entities: {total}")
    print(f"With real summaries: {with_summary}")
    print(f"With None yet/empty: {none_yet}")
    print(f"Percentage with real summaries: {with_summary/total*100:.1f}%")

    # Sample some entities that need summaries
    result3 = session.run(
        """
        MATCH (e:Entity)
        WHERE e.summary IS NULL OR e.summary = '' OR e.summary = 'None yet.'
        RETURN e.name as name, e.summary as summary
        LIMIT 5
    """
    )
    print("\nSample entities needing summaries:")
    for record in result3:
        print(f'  - {record["name"]}: "{record["summary"]}"')

driver.close()
