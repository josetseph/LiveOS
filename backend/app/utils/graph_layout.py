"""
Hierarchical 3D layout computation for the knowledge graph.

Algorithm:
  1. Level-2 communities (most specific) are placed on a large Fibonacci sphere.
  2. Member nodes are distributed on a smaller sphere centred at their community.
  3. Level-0 and level-1 community positions are the centroid of their positioned
     members (computed after step 2).
  4. Nodes with no community assignment are placed on a fallback inner sphere so
     they are always visible, even before communities have been computed.

The result is a static dict {node_id: (x, y, z)} that is stored in Kuzu so
the frontend never has to run a physics simulation.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Helpers ──────────────────────────────────────────────────────────────────


def _fibonacci_sphere(n: int, radius: float) -> list[tuple[float, float, float]]:
    """Return n evenly-distributed points on the surface of a sphere."""
    if n <= 0:
        return []
    points: list[tuple[float, float, float]] = []
    golden = math.pi * (math.sqrt(5.0) - 1.0)  # golden angle in radians
    for i in range(n):
        y = 1.0 - (i / max(n - 1, 1)) * 2.0
        r = math.sqrt(1.0 - y * y)
        theta = golden * i
        x = math.cos(theta) * r
        z = math.sin(theta) * r
        points.append((x * radius, y * radius, z * radius))
    return points


def _deterministic_jitter(seed: str, max_offset: float) -> tuple[float, float, float]:
    """Produce a stable small offset from a string seed to avoid z-fighting."""
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    jx = ((h & 0xFF) / 255.0 - 0.5) * 2.0 * max_offset
    jy = (((h >> 8) & 0xFF) / 255.0 - 0.5) * 2.0 * max_offset
    jz = (((h >> 16) & 0xFF) / 255.0 - 0.5) * 2.0 * max_offset
    return jx, jy, jz


def _centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Return the average position of a non-empty list of 3D points."""
    n = len(points)
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


# ── Constants ────────────────────────────────────────────────────────────────

UNIVERSE_RADIUS = 1200.0  # radius of the top-level sphere
CLUSTER_RADIUS_BASE = 120.0  # base radius of each community cluster sphere
ORPHAN_RADIUS = 600.0  # fallback sphere radius for unclustered nodes

# Solar-system layout constants
#
# Orbit depth ratio per level: ~4× between successive levels so hierarchy is
# clearly visible at any zoom. For the most-common case (1 L2 per L1, 8 nodes):
#   node cluster ≈ 50 units  (moon cloud around L2 planet)
#   L2 orbit     = 150 units (L2 planet around L1 star)  → 3× node
#   L1 orbit     = 500 units (L1 star around L0 galaxy)  → 3.3× L2+node radius
#
SOLAR_UNIVERSE_RADIUS = 1800.0  # L0 galaxies placed on this sphere
SOLAR_L0_RING_BASE = 500.0  # L1 orbit radius (per sqrt of child count)
SOLAR_L0_RING_MAX = 1200.0
SOLAR_L1_RING_BASE = 150.0  # L2 orbit radius around L1 star
SOLAR_L1_RING_MAX = 400.0
SOLAR_L2_NODE_BASE = 18.0  # node orbit radius (per sqrt of member count)
SOLAR_L2_NODE_MAX = 55.0


# ── Public API ───────────────────────────────────────────────────────────────


def compute_positions(
    communities: list[dict],
    memberships: dict[str, list[str]],
    all_node_ids: list[str] | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Compute stable 3D positions for all nodes and community nodes.

    Args:
        communities:   list of community dicts, each must have
                       ``community_id``, ``community_level``, ``name``
        memberships:   {community_id: [node_id, ...]} for level-2 communities
                       (most-specific assignments only)
        all_node_ids:  optional full list of regular node IDs so unclustered
                       nodes are placed on a fallback sphere and always visible

    Returns:
        {node_id_or_community_id: (x, y, z)}
    """
    positions: dict[str, tuple[float, float, float]] = {}

    # ── 1. Level-2 cluster centres on the universe sphere ────────────────────
    level2 = [
        c
        for c in communities
        if c.get("community_level") == 2 and memberships.get(c["community_id"])
    ]

    root_pts = _fibonacci_sphere(len(level2), UNIVERSE_RADIUS)
    community_centres: dict[str, tuple[float, float, float]] = {}

    for i, community in enumerate(level2):
        cid = community["community_id"]
        cx, cy, cz = root_pts[i]
        jx, jy, jz = _deterministic_jitter(cid, 5.0)
        centre = (cx + jx, cy + jy, cz + jz)
        community_centres[cid] = centre
        positions[cid] = centre

    # ── 2. Member nodes distributed around their level-2 centre ─────────────
    for community in level2:
        cid = community["community_id"]
        members = memberships.get(cid, [])
        if not members:
            continue

        cx, cy, cz = community_centres[cid]
        cluster_radius = CLUSTER_RADIUS_BASE * math.sqrt(max(len(members), 1))
        cluster_radius = min(cluster_radius, CLUSTER_RADIUS_BASE * 8)

        member_pts = _fibonacci_sphere(len(members), cluster_radius)
        for j, node_id in enumerate(members):
            px, py, pz = member_pts[j]
            jx, jy, jz = _deterministic_jitter(node_id, 3.0)
            positions[node_id] = (cx + px + jx, cy + py + jy, cz + pz + jz)

    # ── 3. Level-0 and level-1 communities → centroid of their members ───────
    # Sort descending by level so level-1 resolves before level-0 (level-0
    # communities may contain level-1 members that are themselves communities).
    coarser = sorted(
        [c for c in communities if c.get("community_level") in (0, 1)],
        key=lambda c: c.get("community_level", 0),
        reverse=True,
    )
    for community in coarser:
        cid = community["community_id"]
        if cid in positions:
            continue
        member_ids = memberships.get(cid) or []
        member_pts_list = [positions[nid] for nid in member_ids if nid in positions]
        if member_pts_list:
            positions[cid] = _centroid(member_pts_list)
        else:
            # No positioned members yet — scatter on the universe sphere with
            # a deterministic offset so it's at least somewhere sensible.
            jx, jy, jz = _deterministic_jitter(cid, UNIVERSE_RADIUS * 0.9)
            positions[cid] = (jx, jy, jz)

    # ── 4. Fallback: unclustered nodes on a separate inner sphere ────────────
    if all_node_ids:
        orphans = [nid for nid in all_node_ids if nid not in positions]
        if orphans:
            orphan_pts = _fibonacci_sphere(len(orphans), ORPHAN_RADIUS)
            for j, node_id in enumerate(orphans):
                ox, oy, oz = orphan_pts[j]
                jx, jy, jz = _deterministic_jitter(node_id, 3.0)
                positions[node_id] = (ox + jx, oy + jy, oz + jz)

    return positions


def compute_solar_positions(
    communities: list[dict],
    node_level_map: dict[str, dict[int, str]],
    all_node_ids: list[str] | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Solar-system hierarchical 3D layout.

    Produces a 4-tier nested-sphere arrangement:

        L0 "stars"   — placed on a large Fibonacci sphere (radius SOLAR_UNIVERSE_RADIUS)
        L1 "planets" — placed on a sphere around their parent L0 star
        L2 "moons"   — placed on a sphere around their parent L1 planet
        Nodes        — placed on a sphere around their parent L2 moon

    The parent of each L2 community is the L1 community that the majority of
    its member nodes belong to (and similarly L1 → L0).  This is inferred
    entirely from ``node_level_map`` without requiring explicit parent edges.

    Args:
        communities:    list of community dicts, each with ``community_id``
                        and ``community_level`` (0 | 1 | 2).
        node_level_map: {node_id: {level: community_id}} — each node's
                        community assignment at every level it belongs to.
        all_node_ids:   optional full list of regular node IDs; nodes not
                        found in any L2 community are placed on a fallback
                        inner sphere.

    Returns:
        {id: (x, y, z)} for every node id and every community id.
    """
    positions: dict[str, tuple[float, float, float]] = {}

    # ── Build community membership lists and parent-vote tallies ─────────────
    l2_members: dict[str, list[str]] = {}  # l2_cid → [node_id, ...]
    l2_l1_votes: dict[str, dict[str, int]] = {}  # l2_cid → {l1_cid: vote_count}
    l1_l0_votes: dict[str, dict[str, int]] = {}  # l1_cid → {l0_cid: vote_count}

    for node_id, level_map in node_level_map.items():
        l2 = level_map.get(2)
        l1 = level_map.get(1)
        l0 = level_map.get(0)
        if l2:
            l2_members.setdefault(l2, []).append(node_id)
            if l1:
                l2_l1_votes.setdefault(l2, {})
                l2_l1_votes[l2][l1] = l2_l1_votes[l2].get(l1, 0) + 1
        if l1 and l0:
            l1_l0_votes.setdefault(l1, {})
            l1_l0_votes[l1][l0] = l1_l0_votes[l1].get(l0, 0) + 1

    # Resolve parent by majority vote
    l2_parent: dict[str, str] = {
        cid: max(votes, key=votes.__getitem__) for cid, votes in l2_l1_votes.items()
    }
    l1_parent: dict[str, str] = {
        cid: max(votes, key=votes.__getitem__) for cid, votes in l1_l0_votes.items()
    }

    # Build children sets (needed for sizing the orbit spheres)
    l0_l1_children: dict[str, list[str]] = {}
    for l1_cid, l0_cid in l1_parent.items():
        l0_l1_children.setdefault(l0_cid, []).append(l1_cid)

    l1_l2_children: dict[str, list[str]] = {}
    for l2_cid, l1_cid in l2_parent.items():
        l1_l2_children.setdefault(l1_cid, []).append(l2_cid)

    # Sort for determinism
    for v in l0_l1_children.values():
        v.sort()
    for v in l1_l2_children.values():
        v.sort()

    # Community id sets by level for quick lookup
    l0_cids = sorted(
        c["community_id"] for c in communities if c.get("community_level") == 0
    )
    l1_cids = sorted(
        c["community_id"] for c in communities if c.get("community_level") == 1
    )
    l2_cids = sorted(
        c["community_id"] for c in communities if c.get("community_level") == 2
    )

    # ── 1. Place L0 stars on the universe sphere ──────────────────────────────
    l0_positions: dict[str, tuple[float, float, float]] = {}
    l0_pts = _fibonacci_sphere(len(l0_cids), SOLAR_UNIVERSE_RADIUS)
    for i, l0_cid in enumerate(l0_cids):
        jx, jy, jz = _deterministic_jitter(l0_cid, 5.0)
        px, py, pz = l0_pts[i]
        pos: tuple[float, float, float] = (px + jx, py + jy, pz + jz)
        l0_positions[l0_cid] = pos
        positions[l0_cid] = pos

    # ── 2. Place L1 planets around their L0 star ──────────────────────────────
    l1_positions: dict[str, tuple[float, float, float]] = {}

    for l0_cid, l1_children in l0_l1_children.items():
        l0_pos = l0_positions.get(l0_cid)
        if not l0_pos:
            continue
        cx, cy, cz = l0_pos
        n = len(l1_children)
        ring_r = min(SOLAR_L0_RING_BASE * math.sqrt(max(n, 1)), SOLAR_L0_RING_MAX)
        pts = _fibonacci_sphere(n, ring_r)
        for i, l1_cid in enumerate(l1_children):
            jx, jy, jz = _deterministic_jitter(l1_cid, 3.0)
            px, py, pz = pts[i]
            pos = (cx + px + jx, cy + py + jy, cz + pz + jz)
            l1_positions[l1_cid] = pos
            positions[l1_cid] = pos

    # Orphan L1s (no L0 parent): scatter on a fallback sphere
    for l1_cid in l1_cids:
        if l1_cid not in l1_positions:
            jx, jy, jz = _deterministic_jitter(l1_cid, SOLAR_UNIVERSE_RADIUS * 0.8)
            pos = (jx, jy, jz)
            l1_positions[l1_cid] = pos
            positions[l1_cid] = pos

    # ── 3. Place L2 moons around their L1 planet ──────────────────────────────
    l2_positions: dict[str, tuple[float, float, float]] = {}

    for l1_cid, l2_children in l1_l2_children.items():
        l1_pos = l1_positions.get(l1_cid)
        if not l1_pos:
            continue
        cx, cy, cz = l1_pos
        n = len(l2_children)
        ring_r = min(SOLAR_L1_RING_BASE * math.sqrt(max(n, 1)), SOLAR_L1_RING_MAX)
        pts = _fibonacci_sphere(n, ring_r)
        for i, l2_cid in enumerate(l2_children):
            jx, jy, jz = _deterministic_jitter(l2_cid, 2.0)
            px, py, pz = pts[i]
            pos = (cx + px + jx, cy + py + jy, cz + pz + jz)
            l2_positions[l2_cid] = pos
            positions[l2_cid] = pos

    # Orphan L2s
    for l2_cid in l2_cids:
        if l2_cid not in l2_positions:
            jx, jy, jz = _deterministic_jitter(l2_cid, SOLAR_UNIVERSE_RADIUS * 0.5)
            pos = (jx, jy, jz)
            l2_positions[l2_cid] = pos
            positions[l2_cid] = pos

    # ── 4. Place nodes around their L2 moon ───────────────────────────────────
    for l2_cid, members in l2_members.items():
        l2_pos = l2_positions.get(l2_cid)
        if not l2_pos:
            continue
        cx, cy, cz = l2_pos
        n = len(members)
        node_r = min(SOLAR_L2_NODE_BASE * math.sqrt(max(n, 1)), SOLAR_L2_NODE_MAX)
        pts = _fibonacci_sphere(n, node_r)
        for i, node_id in enumerate(sorted(members)):
            jx, jy, jz = _deterministic_jitter(node_id, 2.0)
            px, py, pz = pts[i]
            positions[node_id] = (cx + px + jx, cy + py + jy, cz + pz + jz)

    # ── 5. Fallback: unclustered nodes ────────────────────────────────────────
    # Nodes that have no L2 assignment (so they weren't placed in step 4) may
    # still belong to an L1 or L0 community.  Group them by their best-known
    # ancestor so they cluster visually near the right part of the graph
    # rather than forming an orphan sphere at the origin.
    if all_node_ids:
        orphans = [nid for nid in all_node_ids if nid not in positions]
        if orphans:
            l1_orphan_groups: dict[str, list[str]] = {}
            l0_orphan_groups: dict[str, list[str]] = {}
            truly_orphan: list[str] = []

            for node_id in orphans:
                level_map = node_level_map.get(node_id, {})
                l1 = level_map.get(1)
                l0 = level_map.get(0)
                if l1 and l1 in l1_positions:
                    l1_orphan_groups.setdefault(l1, []).append(node_id)
                elif l0 and l0 in l0_positions:
                    l0_orphan_groups.setdefault(l0, []).append(node_id)
                else:
                    truly_orphan.append(node_id)

            # Cluster around L1 center (like loose moons that lost their L2)
            for l1_cid, members in l1_orphan_groups.items():
                cx, cy, cz = l1_positions[l1_cid]
                n = len(members)
                node_r = min(
                    SOLAR_L1_RING_BASE * 0.7 * math.sqrt(max(n, 1)),
                    SOLAR_L1_RING_MAX * 0.5,
                )
                pts = _fibonacci_sphere(n, node_r)
                for i, node_id in enumerate(sorted(members)):
                    jx, jy, jz = _deterministic_jitter(node_id, 2.0)
                    px, py, pz = pts[i]
                    positions[node_id] = (cx + px + jx, cy + py + jy, cz + pz + jz)

            # Cluster around L0 center (loosest — just needs to be in the right galaxy)
            for l0_cid, members in l0_orphan_groups.items():
                cx, cy, cz = l0_positions[l0_cid]
                n = len(members)
                node_r = min(
                    SOLAR_L0_RING_BASE * 0.4 * math.sqrt(max(n, 1)),
                    SOLAR_L0_RING_MAX * 0.3,
                )
                pts = _fibonacci_sphere(n, node_r)
                for i, node_id in enumerate(sorted(members)):
                    jx, jy, jz = _deterministic_jitter(node_id, 2.0)
                    px, py, pz = pts[i]
                    positions[node_id] = (cx + px + jx, cy + py + jy, cz + pz + jz)

            # Truly orphan — scatter as asteroids throughout the universe volume.
            # We use a hash-derived spherical coordinate where r is spread across
            # the full universe depth (not a surface), so they appear as background
            # asteroids between star systems rather than a solid central sphere.
            if truly_orphan:
                _MAX_R = SOLAR_UNIVERSE_RADIUS * 1.4
                _MIN_R = 80.0
                for node_id in truly_orphan:
                    h = int(hashlib.md5(node_id.encode()).hexdigest(), 16)
                    # Uniform point on unit sphere (rejection-free method)
                    cos_theta = ((h & 0xFFFF) / 65535.0) * 2.0 - 1.0
                    phi = ((h >> 16) & 0xFFFF) / 65535.0 * 2.0 * math.pi
                    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
                    nx = sin_theta * math.cos(phi)
                    ny = cos_theta
                    nz = sin_theta * math.sin(phi)
                    # r uniformly distributed across volume (cube-root gives uniform 3D density)
                    r_frac = ((h >> 32) & 0xFFFFFF) / float(0xFFFFFF)
                    r = _MIN_R + (r_frac ** (1.0 / 3.0)) * (_MAX_R - _MIN_R)
                    positions[node_id] = (nx * r, ny * r, nz * r)

    return positions


def compute_spring_layout_3d(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    k: float = 220.0,
    iterations: int = 80,
    gravity: float = 0.02,
) -> dict[str, tuple[float, float, float]]:
    """3D Fruchterman-Reingold spring layout.

    Connected nodes are pulled together (attraction ∝ d²/k).
    All node pairs are pushed apart (repulsion ∝ k²/d).
    A gentle gravity toward origin prevents runaway nodes.

    Args:
        node_ids:   All nodes to lay out (Indexable + Community).
        edges:      List of (source_id, target_id) pairs.
        k:          Ideal edge length in world units (~distance between
                    connected neighbours at equilibrium).
        iterations: Number of simulation steps.
        gravity:    Pull toward origin per unit distance (0 = no gravity).

    Returns:
        {node_id: (x, y, z)}
    """
    import math

    n = len(node_ids)
    if n == 0:
        return {}
    if n == 1:
        return {node_ids[0]: (0.0, 0.0, 0.0)}

    # ── Initial positions on a Fibonacci sphere so layout is deterministic ───
    pos: dict[str, list[float]] = {}
    golden = math.pi * (math.sqrt(5.0) - 1.0)
    init_radius = k * max(n ** (1 / 3), 1.5)
    for i, nid in enumerate(node_ids):
        y = 1.0 - (i / max(n - 1, 1)) * 2.0
        r = math.sqrt(max(1.0 - y * y, 0.0))
        theta = golden * i
        pos[nid] = [
            math.cos(theta) * r * init_radius,
            y * init_radius,
            math.sin(theta) * r * init_radius,
        ]

    # ── Build undirected unique-edge set ────────────────────────────────────
    node_set = set(node_ids)
    adj: set[tuple[str, str]] = set()
    for src, tgt in edges:
        if src in node_set and tgt in node_set and src != tgt:
            a, b = (src, tgt) if src < tgt else (tgt, src)
            adj.add((a, b))
    adj_list = list(adj)

    # ── FR iterations with cosine cooling ───────────────────────────────────
    t_start = k * 2.5
    for step in range(iterations):
        # Cosine cool: fast at first, smooth near convergence
        progress = step / iterations
        t = t_start * (0.5 + 0.5 * math.cos(math.pi * progress))

        disp: dict[str, list[float]] = {nid: [0.0, 0.0, 0.0] for nid in node_ids}

        # Repulsion: O(n²) — acceptable for n ≤ 500
        for i in range(n):
            for j in range(i + 1, n):
                u, v = node_ids[i], node_ids[j]
                dx = pos[u][0] - pos[v][0]
                dy = pos[u][1] - pos[v][1]
                dz = pos[u][2] - pos[v][2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
                f = (k * k) / d  # repulsion magnitude
                nx_, ny_, nz_ = dx / d, dy / d, dz / d
                disp[u][0] += nx_ * f
                disp[u][1] += ny_ * f
                disp[u][2] += nz_ * f
                disp[v][0] -= nx_ * f
                disp[v][1] -= ny_ * f
                disp[v][2] -= nz_ * f

        # Attraction along edges
        for src, tgt in adj_list:
            dx = pos[src][0] - pos[tgt][0]
            dy = pos[src][1] - pos[tgt][1]
            dz = pos[src][2] - pos[tgt][2]
            d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
            f = (d * d) / k  # attraction magnitude
            nx_, ny_, nz_ = dx / d, dy / d, dz / d
            disp[src][0] -= nx_ * f
            disp[src][1] -= ny_ * f
            disp[src][2] -= nz_ * f
            disp[tgt][0] += nx_ * f
            disp[tgt][1] += ny_ * f
            disp[tgt][2] += nz_ * f

        # Gravity toward origin
        if gravity > 0:
            for nid in node_ids:
                disp[nid][0] -= pos[nid][0] * gravity
                disp[nid][1] -= pos[nid][1] * gravity
                disp[nid][2] -= pos[nid][2] * gravity

        # Apply displacement, capped by temperature
        for nid in node_ids:
            dx, dy, dz = disp[nid]
            d = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.01
            move = min(d, t)
            pos[nid][0] += (dx / d) * move
            pos[nid][1] += (dy / d) * move
            pos[nid][2] += (dz / d) * move

    return {
        nid: (float(pos[nid][0]), float(pos[nid][1]), float(pos[nid][2]))
        for nid in node_ids
    }
