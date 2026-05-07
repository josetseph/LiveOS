#!/usr/bin/env python3
"""
Knowledge Graph Analysis Script
================================
Analyses a Neo4j PKM knowledge graph and produces:
  • Quantitative metrics (node/edge counts, degree stats, path lengths,
    density, clustering, connectivity, relationship richness, etc.)
  • 8 Matplotlib figures saved as PNG
  • A filled-in Markdown research report

Reusable for any Neo4j-backed graph — edit the CONFIG block at the top
to change which labels / relationship types are included or excluded.

Usage:
    # Full run (default output dir: graph_analysis/)
    python scripts/analyze_graph.py

    # Custom output directory
    python scripts/analyze_graph.py --out-dir reports/my_dataset

    # Fewer path-length samples (faster, less accurate)
    python scripts/analyze_graph.py --sample 200

    # Skip figure generation (fast — numbers only)
    python scripts/analyze_graph.py --no-viz

    # Custom dataset name in the report
    python scripts/analyze_graph.py --dataset "My Knowledge Graph v2"
"""

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

# ── path bootstrap ────────────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib

matplotlib.use("Agg")  # headless — no display required
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from app.services.graph import graph_service
from matplotlib.patches import Patch

# ═════════════════════════════════════════════════════════════════════════════
# CONFIG — edit these to adapt the script to a different dataset / Kuzu schema
# ═════════════════════════════════════════════════════════════════════════════

# Node labels to include.  None = include everything.
INCLUDE_LABELS = None  # e.g. ["Entity", "Concept", "Reference"]

# Node labels to exclude entirely (e.g. internal scaffolding)
EXCLUDE_LABELS = {"Indexable"}

# Relationship types treated as structural scaffolding (Note ↔ Knowledge links).
# They are tallied separately from domain / semantic relationships.
STRUCTURAL_REL_TYPES = {"MENTIONS", "CONTRIBUTES_TO", "CITES", "PRODUCES_TASK"}

# Relationship types that represent identity / alias links
ALIAS_REL_TYPES = {"IS_SAME_AS", "IS_VARIANT_OF", "IS_SIMILAR_TO", "RELATED_TO"}

# Colour palette for node labels in figures (extend as needed)
LABEL_COLOURS = {
    "Entity": "#4C72B0",
    "Concept": "#55A868",
    "Note": "#AAAAAA",
    "Reference": "#C44E52",
    "Task": "#DD8452",
    "Community": "#937DC2",
    "Persona": "#8172B3",
    "Indexable": "#CCCCCC",
}
DEFAULT_NODE_COLOUR = "#888888"

# Number of random source nodes for path-length BFS sampling
DEFAULT_PATH_SAMPLES = 500

# Top-N hubs shown in the hub subgraph figure
HUB_SUBGRAPH_N = 30


# ═════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═════════════════════════════════════════════════════════════════════════════


def load_graph_from_kuzu() -> tuple:
    """
    Pull all nodes and active relationships from Kuzu.
    Returns (DiGraph, meta_dict).
    meta_dict contains the raw row lists for any downstream use.
    """
    print("  Loading nodes …")
    node_rows = graph_service.execute_query(
        """
        MATCH (n:Node)
        WHERE n.kind NOT IN $exclude AND n.id IS NOT NULL
        RETURN
            n.id     AS nid,
            n.kind   AS label,
            COALESCE(n.name, n.id) AS display_name,
            n.type   AS entity_type
        """,
        {"exclude": list(EXCLUDE_LABELS)},
    )

    print("  Loading relationships …")
    rel_rows = graph_service.execute_query(
        """
        MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
        WHERE a.kind NOT IN $exclude
          AND b.kind NOT IN $exclude
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN
            a.id                            AS src,
            b.id                            AS tgt,
            r.rel_type                      AS rel_type,
            COALESCE(r.confidence, 1.0)     AS confidence,
            a.kind                          AS src_label,
            b.kind                          AS tgt_label
        """,
        {"exclude": list(EXCLUDE_LABELS)},
    )

    G = nx.DiGraph()

    for row in node_rows:
        label = row["label"] or "Unknown"
        if INCLUDE_LABELS and label not in INCLUDE_LABELS:
            continue
        G.add_node(
            row["nid"],
            label=label,
            name=row["display_name"] or "",
            entity_type=row["entity_type"] or "",
            summary="",
        )

    for row in rel_rows:
        src, tgt = row["src"], row["tgt"]
        if src not in G.nodes or tgt not in G.nodes:
            continue
        G.add_edge(
            src,
            tgt,
            rel_type=row["rel_type"],
            confidence=float(row["confidence"] or 1.0),
            context="",
            src_label=row["src_label"] or "",
            tgt_label=row["tgt_label"] or "",
        )

    return G, {"node_rows": node_rows, "rel_rows": rel_rows}


# ═════════════════════════════════════════════════════════════════════════════
# METRICS
# ═════════════════════════════════════════════════════════════════════════════


def compute_basic_stats(G: nx.DiGraph) -> dict:
    node_label_counts = Counter(d["label"] for _, d in G.nodes(data=True))
    rel_type_counts = Counter(d["rel_type"] for _, _, d in G.edges(data=True))

    structural_count = sum(
        v for k, v in rel_type_counts.items() if k in STRUCTURAL_REL_TYPES
    )
    alias_count = sum(v for k, v in rel_type_counts.items() if k in ALIAS_REL_TYPES)
    semantic_count = sum(
        v
        for k, v in rel_type_counts.items()
        if k not in STRUCTURAL_REL_TYPES and k not in ALIAS_REL_TYPES
    )

    # Cross-label relationship matrix
    cross = defaultdict(int)
    for _, _, d in G.edges(data=True):
        cross[(d["src_label"], d["tgt_label"])] += 1

    return {
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "node_label_counts": dict(node_label_counts),
        "rel_type_counts": rel_type_counts.most_common(),  # list of (type, count)
        "structural_count": structural_count,
        "alias_count": alias_count,
        "semantic_count": semantic_count,
        "n_rel_types": len(rel_type_counts),
        "cross_label_counts": dict(cross),
        "density": nx.density(G),
    }


def _array_stats(seq) -> dict:
    a = np.array(seq, dtype=float)
    if len(a) == 0:
        return {
            k: 0
            for k in ("min", "max", "mean", "median", "std", "p25", "p75", "p90", "p99")
        }
    return {
        "min": int(a.min()),
        "max": int(a.max()),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "std": float(a.std()),
        "p25": float(np.percentile(a, 25)),
        "p75": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
        "p99": float(np.percentile(a, 99)),
    }


def compute_degree_stats(G: nx.DiGraph) -> dict:
    UG = G.to_undirected()
    degrees = [d for _, d in UG.degree()]
    in_degrees = [d for _, d in G.in_degree()]
    out_degrees = [d for _, d in G.out_degree()]

    top_hubs = sorted(UG.degree(), key=lambda x: x[1], reverse=True)
    hub_details = [
        {
            "name": G.nodes[n].get("name", str(n)),
            "label": G.nodes[n].get("label", ""),
            "degree": deg,
        }
        for n, deg in top_hubs
    ]

    return {
        "degree": _array_stats(degrees),
        "in_degree": _array_stats(in_degrees),
        "out_degree": _array_stats(out_degrees),
        "degree_seq": degrees,  # raw list — used by figures
        "top_hubs": hub_details,
        "zero_degree_nodes": sum(1 for d in degrees if d == 0),
    }


def compute_connectivity(G: nx.DiGraph) -> dict:
    UG = G.to_undirected()
    wccs = list(nx.weakly_connected_components(G))
    sccs = list(nx.strongly_connected_components(G))
    ucomp = list(nx.connected_components(UG))

    largest_wcc = max(len(c) for c in wccs)
    largest_scc = max(len(c) for c in sccs)

    return {
        "n_wcc": len(wccs),
        "largest_wcc_nodes": largest_wcc,
        "largest_wcc_pct": largest_wcc / G.number_of_nodes() * 100,
        "n_scc": len(sccs),
        "largest_scc_nodes": largest_scc,
        "largest_scc_pct": largest_scc / G.number_of_nodes() * 100,
        "n_isolated": sum(1 for c in ucomp if len(c) == 1),
    }


def compute_path_lengths(G: nx.DiGraph, n_samples: int = DEFAULT_PATH_SAMPLES) -> dict:
    """
    BFS-sample shortest paths from random nodes in the Largest Connected Component.
    Exact diameter is NP-hard to compute at scale; this gives a reliable estimate.
    """
    UG = G.to_undirected()
    wccs = sorted(nx.connected_components(UG), key=len, reverse=True)
    lcc = UG.subgraph(wccs[0]).copy()
    nodes = list(lcc.nodes())

    sample_size = min(n_samples, len(nodes))
    sampled = random.sample(nodes, sample_size)

    all_lengths = []
    print(f"    Sampling from {sample_size:,} sources in LCC ({len(nodes):,} nodes) …")
    for i, src in enumerate(sampled):
        if i % 100 == 0 and i > 0:
            print(f"      … {i}/{sample_size}")
        lengths = nx.single_source_shortest_path_length(lcc, src)
        all_lengths.extend(v for k, v in lengths.items() if k != src)

    arr = np.array(all_lengths, dtype=int)
    dist = dict(Counter(arr.tolist()))

    return {
        "lcc_nodes": len(nodes),
        "n_samples": sample_size,
        "n_path_obs": len(all_lengths),
        "min": int(arr.min()),
        "max": int(arr.max()),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std()),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "effective_diameter_90": float(np.percentile(arr, 90)),
        "effective_diameter_95": float(np.percentile(arr, 95)),
        "diameter_estimate": int(arr.max()),
        "path_length_dist": dist,
    }


def compute_clustering(G: nx.DiGraph) -> dict:
    UG = G.to_undirected()
    return {
        "avg_clustering_coeff": nx.average_clustering(UG),
        "transitivity": nx.transitivity(UG),
    }


def compute_relationship_richness(G: nx.DiGraph) -> dict:
    """Per-node relationship type diversity and edge-context coverage."""
    types_per_node = defaultdict(set)
    for u, v, d in G.edges(data=True):
        types_per_node[u].add(d["rel_type"])
        types_per_node[v].add(d["rel_type"])

    diversities = [len(v) for v in types_per_node.values()]
    arr = np.array(diversities, dtype=float) if diversities else np.array([0.0])

    context_edges = sum(
        1 for _, _, d in G.edges(data=True) if d.get("context", "").strip()
    )
    conf_values = [d["confidence"] for _, _, d in G.edges(data=True)]
    conf_arr = np.array(conf_values, dtype=float) if conf_values else np.array([1.0])

    return {
        "rel_diversity_mean": float(arr.mean()),
        "rel_diversity_max": int(arr.max()),
        "nodes_with_edges": len(types_per_node),
        "context_edges": context_edges,
        "context_edge_pct": context_edges / max(G.number_of_edges(), 1) * 100,
        "mean_confidence": float(conf_arr.mean()),
        "min_confidence": float(conf_arr.min()),
    }


# ═════════════════════════════════════════════════════════════════════════════
# FIGURES
# ═════════════════════════════════════════════════════════════════════════════


def _label_colour(label: str) -> str:
    return LABEL_COLOURS.get(label, DEFAULT_NODE_COLOUR)


def fig_node_distribution(stats: dict, out_path: str):
    counts = stats["node_label_counts"]
    labels = sorted(counts, key=counts.get, reverse=True)
    values = [counts[l] for l in labels]
    colours = [_label_colour(l) for l in labels]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(labels, values, color=colours, edgecolor="white", linewidth=0.8)
    ax.bar_label(bars, fmt="%d", padding=3, fontsize=9)
    ax.set_title("Node Count by Label", fontsize=13, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_xlabel("Node Label")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_relationship_types(stats: dict, out_path: str, top_n: int = 30):
    top = stats["rel_type_counts"][:top_n]
    names = [t for t, _ in top]
    values = [v for _, v in top]

    def _rc(name):
        if name in STRUCTURAL_REL_TYPES:
            return "#AAAAAA"
        if name in ALIAS_REL_TYPES:
            return "#DD8452"
        return "#4C72B0"

    colours = [_rc(n) for n in names]
    fig, ax = plt.subplots(figsize=(10, max(6, top_n * 0.32)))
    y = range(len(names))
    ax.barh(list(y), values, color=colours, edgecolor="white")
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_title(f"Top {top_n} Relationship Types", fontsize=13, fontweight="bold")
    ax.set_xlabel("Count")
    ax.spines[["top", "right"]].set_visible(False)
    legend_els = [
        Patch(facecolor="#AAAAAA", label="Structural"),
        Patch(facecolor="#DD8452", label="Alias / Identity"),
        Patch(facecolor="#4C72B0", label="Semantic / Domain"),
    ]
    ax.legend(handles=legend_els, loc="lower right", fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_rel_category_breakdown(stats: dict, out_path: str):
    categories = {
        "Structural\n(Note↔Knowledge)": stats["structural_count"],
        "Alias / Identity": stats["alias_count"],
        "Semantic / Domain": stats["semantic_count"],
    }
    labels = list(categories.keys())
    values = list(categories.values())
    colours = ["#AAAAAA", "#DD8452", "#4C72B0"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    wedges, texts, autotexts = ax1.pie(
        values,
        labels=labels,
        colors=colours,
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.7,
        textprops={"fontsize": 9},
    )
    ax1.set_title("Relationship Category Split", fontweight="bold")

    bars = ax2.bar(range(len(labels)), values, color=colours, edgecolor="white")
    ax2.bar_label(bars, fmt="%d", padding=3, fontsize=9)
    ax2.set_xticks(range(len(labels)))
    ax2.set_xticklabels(labels, fontsize=8)
    ax2.set_ylabel("Count")
    ax2.set_title("Absolute Counts", fontweight="bold")
    ax2.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_degree_distribution(degree_stats: dict, out_path: str):
    degrees = degree_stats["degree_seq"]
    dmean = degree_stats["degree"]["mean"]
    dmedian = degree_stats["degree"]["median"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Linear histogram
    ax = axes[0]
    ax.hist(degrees, bins=50, color="#4C72B0", edgecolor="white", alpha=0.9)
    ax.axvline(dmean, color="red", linestyle="--", label=f"Mean {dmean:.1f}")
    ax.axvline(dmedian, color="orange", linestyle="--", label=f"Median {dmedian:.1f}")
    ax.set_xlabel("Degree")
    ax.set_ylabel("Node Count")
    ax.set_title("Degree Distribution (linear)", fontweight="bold")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    # Log-log
    ax = axes[1]
    cnt = Counter(degrees)
    xs = sorted(cnt.keys())
    ys = [cnt[x] for x in xs]
    ax.loglog(xs, ys, "o", markersize=4, color="#4C72B0", alpha=0.7)
    ax.set_xlabel("Degree (log)")
    ax.set_ylabel("Count (log)")
    ax.set_title("Degree Distribution (log–log)", fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_degree_ccdf(degree_stats: dict, out_path: str):
    """Complementary CDF — a straight line in log-log space indicates power-law degree."""
    degrees = sorted(degree_stats["degree_seq"], reverse=True)
    n = len(degrees)
    ccdf = np.arange(1, n + 1) / n

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.loglog(degrees, ccdf, linewidth=1.5, color="#4C72B0")
    ax.set_xlabel("Degree k (log scale)")
    ax.set_ylabel("P(Degree ≥ k)")
    ax.set_title("Degree CCDF — Power-Law Check", fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_path_length_distribution(path_stats: dict, out_path: str):
    dist = path_stats["path_length_dist"]
    lengths = sorted(dist.keys())
    counts = [dist[l] for l in lengths]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(lengths, counts, color="#55A868", edgecolor="white")
    ax.axvline(
        path_stats["mean"],
        color="red",
        linestyle="--",
        linewidth=1.5,
        label=f"Mean {path_stats['mean']:.2f}",
    )
    ax.axvline(
        path_stats["median"],
        color="orange",
        linestyle="--",
        linewidth=1.5,
        label=f"Median {path_stats['median']:.0f}",
    )
    ax.set_xlabel("Shortest Path Length")
    ax.set_ylabel("Frequency")
    ax.set_title(
        f"Shortest Path Length Distribution\n"
        f"({path_stats['n_samples']:,} sampled sources, "
        f"{path_stats['n_path_obs']:,} observations, LCC only)",
        fontweight="bold",
    )
    ax.legend(fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_cross_label_heatmap(stats: dict, out_path: str):
    cross = stats["cross_label_counts"]
    all_labels = sorted({lbl for pair in cross for lbl in pair})
    n = len(all_labels)

    matrix = np.zeros((n, n), dtype=int)
    for (src_l, tgt_l), cnt in cross.items():
        if src_l in all_labels and tgt_l in all_labels:
            i = all_labels.index(src_l)
            j = all_labels.index(tgt_l)
            matrix[i, j] = cnt

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(all_labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(all_labels, fontsize=9)
    ax.set_title("Cross-Label Relationship Count (source → target)", fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.8)

    vmax = matrix.max()
    for i in range(n):
        for j in range(n):
            v = matrix[i, j]
            if v > 0:
                ax.text(
                    j,
                    i,
                    f"{v:,}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black" if v < vmax * 0.6 else "white",
                )

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


def fig_hub_subgraph(G: nx.DiGraph, degree_stats: dict, out_path: str):
    UG = G.to_undirected()
    top_ids = [
        n
        for n, _ in sorted(UG.degree(), key=lambda x: x[1], reverse=True)[
            :HUB_SUBGRAPH_N
        ]
    ]

    subgraph_nodes = set(top_ids)
    for h in top_ids:
        subgraph_nodes.update(UG.neighbors(h))
        if len(subgraph_nodes) > 300:
            break

    sub = UG.subgraph(subgraph_nodes).copy()
    deg_map = dict(sub.degree())
    max_deg = max(deg_map.values()) if deg_map else 1
    sizes = [200 + 1800 * (deg_map[n] / max_deg) ** 1.5 for n in sub.nodes()]
    colours = [_label_colour(sub.nodes[n].get("label", "")) for n in sub.nodes()]

    fig, ax = plt.subplots(figsize=(16, 14))
    pos = nx.spring_layout(sub, seed=42, k=1.6 / math.sqrt(max(len(sub), 1)))

    nx.draw_networkx_edges(sub, pos, ax=ax, alpha=0.12, width=0.5, edge_color="#888888")
    nx.draw_networkx_nodes(
        sub, pos, ax=ax, node_size=sizes, node_color=colours, alpha=0.85
    )

    hub_labels = {n: G.nodes[n].get("name", "")[:22] for n in top_ids if n in sub}
    nx.draw_networkx_labels(
        sub, pos, labels=hub_labels, ax=ax, font_size=6, font_weight="bold"
    )

    legend_els = [
        Patch(facecolor=c, label=l)
        for l, c in LABEL_COLOURS.items()
        if l not in EXCLUDE_LABELS
    ]
    ax.legend(handles=legend_els, loc="lower right", fontsize=8)
    ax.set_title(
        f"Hub Subgraph — Top {HUB_SUBGRAPH_N} Hubs + Immediate Neighbours\n"
        f"(node size ∝ degree²; {len(sub)} nodes shown)",
        fontweight="bold",
        fontsize=13,
    )
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    saved {os.path.basename(out_path)}")


# ═════════════════════════════════════════════════════════════════════════════
# MARKDOWN REPORT
# ═════════════════════════════════════════════════════════════════════════════


def write_markdown_report(
    stats: dict,
    degree_stats: dict,
    conn_stats: dict,
    path_stats: dict,
    clustering: dict,
    richness: dict,
    figures: dict,
    out_path: str,
    dataset_name: str = "Knowledge Graph",
):
    d = stats
    ds = degree_stats
    cs = conn_stats
    ps = path_stats
    cl = clustering
    ri = richness

    n_nodes = d["n_nodes"]
    n_edges = d["n_edges"]

    # Expected mean path length under random graph assumption:
    # ~ log(N) / log(mean_k)
    mean_k = ds["degree"]["mean"]
    expected_mean_path = math.log(ps["lcc_nodes"]) / math.log(max(mean_k, 1.001))
    small_world_ratio = cl["avg_clustering_coeff"] / max(d["density"], 1e-9)

    # Node distribution table rows
    node_table = "\n".join(
        f"| {lbl} | {cnt:,} | {cnt/n_nodes*100:.1f}% |"
        for lbl, cnt in sorted(d["node_label_counts"].items(), key=lambda x: -x[1])
    )

    # Top 20 relationship type rows
    rel_table = "\n".join(
        f"| `{rtype}` | {cnt:,} | "
        f"{'Structural' if rtype in STRUCTURAL_REL_TYPES else 'Alias' if rtype in ALIAS_REL_TYPES else 'Semantic'} |"
        for rtype, cnt in d["rel_type_counts"][:20]
    )

    # Top 15 hub rows
    hub_table = "\n".join(
        f"| {i+1} | {h['name'][:45]} | {h['label']} | {h['degree']:,} |"
        for i, h in enumerate(ds["top_hubs"][:15])
    )

    # Path length distribution table
    path_dist_table = "\n".join(
        f"| {length} | {count:,} | {count/ps['n_path_obs']*100:.1f}% |"
        for length, count in sorted(ps["path_length_dist"].items())
    )

    report = f"""# Knowledge Graph Analysis Report

**Dataset:** {dataset_name}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Analysis script:** `scripts/analyze_graph.py`

---

## Summary

| Metric | Value |
|--------|------:|
| Total Nodes | {n_nodes:,} |
| Total Edges (directed) | {n_edges:,} |
| Distinct Relationship Types | {d['n_rel_types']} |
| Graph Density | {d['density']:.6f} |
| Mean Degree (undirected) | {ds['degree']['mean']:.2f} |
| Mean Shortest Path Length | {ps['mean']:.3f} |
| Estimated Diameter | {ps['diameter_estimate']} |
| Largest WCC | {cs['largest_wcc_pct']:.1f}% of nodes |
| Avg Clustering Coefficient | {cl['avg_clustering_coeff']:.4f} |

---

## 1. Node Distribution

| Label | Count | % of Total |
|-------|------:|----------:|
{node_table}

![Node Distribution]({figures['node_dist']})

---

## 2. Relationship Structure

**Total distinct relationship types:** {d['n_rel_types']}

| Category | Count | % of Edges |
|----------|------:|----------:|
| Structural (Note↔Knowledge links) | {d['structural_count']:,} | {d['structural_count']/n_edges*100:.1f}% |
| Alias / Identity (IS_SAME_AS…) | {d['alias_count']:,} | {d['alias_count']/n_edges*100:.1f}% |
| Semantic / Domain relationships | {d['semantic_count']:,} | {d['semantic_count']/n_edges*100:.1f}% |

### Top 20 Relationship Types

| Relationship | Count | Category |
|-------------|------:|---------|
{rel_table}

![Relationship Types]({figures['rel_types']})

![Relationship Categories]({figures['rel_cats']})

---

## 3. Degree Statistics

### Undirected Degree (edges in + out, treating graph as undirected)

| Metric | Value |
|--------|------:|
| Minimum | {ds['degree']['min']} |
| Maximum | {ds['degree']['max']} |
| Mean | {ds['degree']['mean']:.2f} |
| Median | {ds['degree']['median']:.1f} |
| Std Dev | {ds['degree']['std']:.2f} |
| 25th percentile | {ds['degree']['p25']:.1f} |
| 75th percentile | {ds['degree']['p75']:.1f} |
| 90th percentile | {ds['degree']['p90']:.1f} |
| 99th percentile | {ds['degree']['p99']:.1f} |
| Isolated nodes (degree 0) | {ds['zero_degree_nodes']:,} |

### In-Degree (directed — edges arriving at a node)

| Metric | Value |
|--------|------:|
| Minimum | {ds['in_degree']['min']} |
| Maximum | {ds['in_degree']['max']} |
| Mean | {ds['in_degree']['mean']:.2f} |
| Median | {ds['in_degree']['median']:.1f} |
| Std Dev | {ds['in_degree']['std']:.2f} |

### Out-Degree (directed — edges leaving a node)

| Metric | Value |
|--------|------:|
| Minimum | {ds['out_degree']['min']} |
| Maximum | {ds['out_degree']['max']} |
| Mean | {ds['out_degree']['mean']:.2f} |
| Median | {ds['out_degree']['median']:.1f} |
| Std Dev | {ds['out_degree']['std']:.2f} |

![Degree Distribution]({figures['degree_dist']})

![Degree CCDF]({figures['degree_ccdf']})

> A straight line in the log–log CCDF plot is consistent with a power-law degree distribution,
> characteristic of scale-free networks (preferential attachment).

---

## 4. Connectivity

| Metric | Value |
|--------|------:|
| Weakly Connected Components (WCC) | {cs['n_wcc']:,} |
| Largest WCC — node count | {cs['largest_wcc_nodes']:,} |
| Largest WCC — % of graph | {cs['largest_wcc_pct']:.2f}% |
| Strongly Connected Components (SCC) | {cs['n_scc']:,} |
| Largest SCC — node count | {cs['largest_scc_nodes']:,} |
| Largest SCC — % of graph | {cs['largest_scc_pct']:.2f}% |
| Isolated nodes (degree 0) | {cs['n_isolated']:,} |

A large WCC ({cs['largest_wcc_pct']:.1f}% of nodes) indicates the graph is well-connected
with most knowledge nodes reachable from one another.

---

## 5. Path Length Statistics

> **Methodology:** BFS from {ps['n_samples']:,} randomly sampled source nodes within the
> Largest Connected Component ({ps['lcc_nodes']:,} nodes). Total observations: {ps['n_path_obs']:,}.
> Note that path lengths are measured on the *undirected* projection of the graph.

| Metric | Value |
|--------|------:|
| Minimum path length | {ps['min']} |
| Maximum observed path | {ps['max']} |
| **Mean path length** | **{ps['mean']:.3f}** |
| Median path length | {ps['median']:.1f} |
| Std Dev | {ps['std']:.3f} |
| 90th percentile | {ps['p90']:.1f} |
| 95th percentile | {ps['p95']:.1f} |
| Effective diameter (90th pct) | {ps['effective_diameter_90']:.1f} |
| Effective diameter (95th pct) | {ps['effective_diameter_95']:.1f} |
| Estimated diameter (max observed) | {ps['diameter_estimate']} |

### Path Length Distribution

| Path Length | Observations | % |
|:-----------:|------------:|--:|
{path_dist_table}

> **Small-world heuristic:** For a random graph with N={ps['lcc_nodes']:,} nodes and
> mean degree k={mean_k:.2f}, the expected mean path length ≈ ln(N)/ln(k) ≈ **{expected_mean_path:.2f}**.
> The observed mean of **{ps['mean']:.2f}** is {'close to' if abs(ps['mean'] - expected_mean_path) < 1 else 'longer than'}
> this expectation, suggesting {'small-world behaviour is present' if ps['mean'] <= expected_mean_path * 1.5 else 'the graph is more hierarchical / less random'}.

![Path Length Distribution]({figures['path_dist']})

---

## 6. Clustering & Local Structure

| Metric | Value |
|--------|------:|
| Average Clustering Coefficient | {cl['avg_clustering_coeff']:.4f} |
| Graph Transitivity (global) | {cl['transitivity']:.4f} |
| Graph Density | {d['density']:.6f} |
| Clustering / Density ratio | {small_world_ratio:.1f}× |

The clustering coefficient ({cl['avg_clustering_coeff']:.4f}) is **{small_world_ratio:.0f}×** the graph
density ({d['density']:.4f}), indicating
{'strong small-world characteristics — nodes cluster locally even though the overall graph is sparse.' if small_world_ratio > 10 else 'moderate local clustering relative to overall sparsity.'}

---

## 7. Top Hub Nodes

Hubs with the highest total (undirected) degree. These nodes act as
information crossroads in the knowledge graph.

| Rank | Name | Label | Degree |
|------|------|-------|-------:|
{hub_table}

![Hub Subgraph]({figures['hub_subgraph']})

---

## 8. Cross-Label Relationship Heatmap

Each cell (row → col) shows how many directed edges go from nodes of
the row label to nodes of the column label.

![Cross-Label Heatmap]({figures['cross_label']})

---

## 9. Relationship Richness

| Metric | Value |
|--------|------:|
| Nodes with ≥ 1 relationship | {ri['nodes_with_edges']:,} |
| Mean relationship types per node | {ri['rel_diversity_mean']:.2f} |
| Max relationship types per node | {ri['rel_diversity_max']} |
| Edges with stored context sentence | {ri['context_edges']:,} ({ri['context_edge_pct']:.1f}%) |
| Mean relationship confidence | {ri['mean_confidence']:.3f} |
| Min relationship confidence | {ri['min_confidence']:.3f} |

---

## 10. Copy-Paste Paragraph (Research Paper)

> The {dataset_name} contains **{n_nodes:,} nodes** distributed across
> {len(d['node_label_counts'])} label types
> (Entity: {d['node_label_counts'].get('Entity', 0):,};
> Concept: {d['node_label_counts'].get('Concept', 0):,};
> Note: {d['node_label_counts'].get('Note', 0):,};
> Reference: {d['node_label_counts'].get('Reference', 0):,};
> Task: {d['node_label_counts'].get('Task', 0):,})
> and **{n_edges:,} directed edges** spanning **{d['n_rel_types']} distinct relationship types**.
> Of the total edges, {d['structural_count']:,} ({d['structural_count']/n_edges*100:.0f}%) are
> structural note-to-knowledge links, {d['alias_count']:,} ({d['alias_count']/n_edges*100:.0f}%) are
> identity or alias relationships, and {d['semantic_count']:,} ({d['semantic_count']/n_edges*100:.0f}%)
> are semantic domain relationships extracted from source content.
> The graph has a density of {d['density']:.4f}, with {cs['largest_wcc_pct']:.1f}% of nodes
> forming a single weakly connected component.
> The mean shortest path length within the largest component is **{ps['mean']:.2f}**
> (effective diameter at the 90th percentile: {ps['effective_diameter_90']:.0f} hops;
> estimated diameter: {ps['diameter_estimate']} hops),
> and the average clustering coefficient is **{cl['avg_clustering_coeff']:.4f}**
> — **{small_world_ratio:.0f}×** the graph density —
> consistent with small-world network topology.
> The average node degree is {ds['degree']['mean']:.2f} (max: {ds['degree']['max']}),
> with the highest-degree node being
> "{ds['top_hubs'][0]['name']}" ({ds['top_hubs'][0]['label']}, degree {ds['top_hubs'][0]['degree']}).

---

*Generated by `scripts/analyze_graph.py` — rerun at any time to refresh all metrics and figures.*
"""

    with open(out_path, "w") as f:
        f.write(report)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Knowledge graph analysis: metrics, figures, and Markdown report."
    )
    parser.add_argument(
        "--out-dir",
        default="graph_analysis",
        help="Output directory for figures and report (default: graph_analysis/)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_PATH_SAMPLES,
        help=f"BFS path-length sample size (default: {DEFAULT_PATH_SAMPLES})",
    )
    parser.add_argument(
        "--no-viz",
        action="store_true",
        help="Skip figure generation (only compute metrics and report)",
    )
    parser.add_argument(
        "--dataset",
        default="LiveOS PKM Graph",
        help="Dataset name used in the report header",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible path-length sampling (default: 42)",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    banner = "=" * 60
    print(f"\n{banner}")
    print(f"  Knowledge Graph Analysis")
    print(f"  Dataset : {args.dataset}")
    print(f"  Output  : {out_dir}")
    print(f"  Samples : {args.sample} (path-length BFS)")
    print(f"{banner}\n")

    t_start = time.perf_counter()

    # ── 1. Load ───────────────────────────────────────────────────────────────
    print("[1/7] Loading graph from Kuzu …")
    G, meta = load_graph_from_kuzu()
    print(
        f"  → {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges "
        f"({time.perf_counter()-t_start:.1f}s)"
    )

    # ── 2–6. Metrics ──────────────────────────────────────────────────────────
    print("\n[2/7] Basic statistics …")
    stats = compute_basic_stats(G)

    print("[3/7] Degree statistics …")
    degree_stats = compute_degree_stats(G)

    print("[4/7] Connectivity …")
    conn_stats = compute_connectivity(G)

    print("[5/7] Path lengths …")
    path_stats = compute_path_lengths(G, n_samples=args.sample)

    print("[6/7] Clustering & richness …")
    clustering = compute_clustering(G)
    richness = compute_relationship_richness(G)

    # ── 7. Figures ────────────────────────────────────────────────────────────
    FIG_FILES = {
        "node_dist": "fig01_node_distribution.png",
        "rel_types": "fig02_relationship_types.png",
        "rel_cats": "fig03_rel_categories.png",
        "degree_dist": "fig04_degree_distribution.png",
        "degree_ccdf": "fig05_degree_ccdf.png",
        "path_dist": "fig06_path_length_distribution.png",
        "cross_label": "fig07_cross_label_heatmap.png",
        "hub_subgraph": "fig08_hub_subgraph.png",
    }
    figures = FIG_FILES.copy()  # relative filenames used in Markdown

    if not args.no_viz:
        print("\n[7/7] Generating figures …")
        fig_node_distribution(stats, os.path.join(out_dir, FIG_FILES["node_dist"]))
        fig_relationship_types(stats, os.path.join(out_dir, FIG_FILES["rel_types"]))
        fig_rel_category_breakdown(stats, os.path.join(out_dir, FIG_FILES["rel_cats"]))
        fig_degree_distribution(
            degree_stats, os.path.join(out_dir, FIG_FILES["degree_dist"])
        )
        fig_degree_ccdf(degree_stats, os.path.join(out_dir, FIG_FILES["degree_ccdf"]))
        fig_path_length_distribution(
            path_stats, os.path.join(out_dir, FIG_FILES["path_dist"])
        )
        fig_cross_label_heatmap(stats, os.path.join(out_dir, FIG_FILES["cross_label"]))
        fig_hub_subgraph(
            G, degree_stats, os.path.join(out_dir, FIG_FILES["hub_subgraph"])
        )
    else:
        print("\n[7/7] Skipping figures (--no-viz)")

    # ── Report ────────────────────────────────────────────────────────────────
    report_path = os.path.join(out_dir, "GRAPH_ANALYSIS_REPORT.md")
    write_markdown_report(
        stats,
        degree_stats,
        conn_stats,
        path_stats,
        clustering,
        richness,
        figures,
        report_path,
        dataset_name=args.dataset,
    )

    # ── Raw JSON dump (all numbers, importable) ────────────────────────────────
    raw_metrics = {
        "basic": {
            **{
                k: v
                for k, v in stats.items()
                if k not in ("rel_type_counts", "cross_label_counts")
            },
            "rel_type_counts": dict(stats["rel_type_counts"]),
            "cross_label_counts": {
                f"{a}__{b}": cnt for (a, b), cnt in stats["cross_label_counts"].items()
            },
        },
        "degree": {k: v for k, v in degree_stats.items() if k != "degree_seq"},
        "connectivity": conn_stats,
        "path_lengths": {
            k: v for k, v in path_stats.items() if k != "path_length_dist"
        },
        "path_length_dist": path_stats["path_length_dist"],
        "clustering": clustering,
        "richness": richness,
        "meta": {
            "dataset": args.dataset,
            "seed": args.seed,
            "generated": datetime.now().isoformat(),
        },
    }
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(raw_metrics, f, indent=2, default=str)

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t_start
    print(f"\n{banner}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Output directory: {out_dir}/")
    print(f"    GRAPH_ANALYSIS_REPORT.md")
    print(f"    metrics.json")
    if not args.no_viz:
        for v in FIG_FILES.values():
            print(f"    {v}")
    print(f"{banner}\n")


if __name__ == "__main__":
    main()
