"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";
import { ShaderBackground } from "@/components/shader-background";
import { nodeColor } from "@/components/graph3d/nodeColors";
import { NodeDetailPanel } from "@/components/graph3d/NodeDetailPanel";
import type { FlatEdge, KnowledgeNode, SelectedEntity } from "@/components/graph3d/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// react-force-graph-2d needs `id` on nodes and `source`/`target` on links.
// Our API uses `node_id` and `edges`, so we remap here.
type GraphNode = KnowledgeNode & { id: string };
type GraphData = { nodes: GraphNode[]; links: FlatEdge[] };

export default function GraphPage() {
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState<SelectedEntity | null>(null);
  const graphRef  = useRef<any>(null);
  const fittedRef = useRef(false);

  useEffect(() => {
    api.getGraph3DFull()
      .then((data) => {
        const nodes = data.nodes
          .filter((n) => n.node_id && n.name?.trim())
          .map((n) => ({ ...n, id: n.node_id }));
        const nodeIds = new Set(nodes.map((n) => n.id));
        // Drop edges that reference a filtered-out (nameless) node — otherwise
        // react-force-graph-2d throws "node not found: <id>"
        const links = data.edges.filter(
          (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
        );
        setGraphData({ nodes, links });
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleNodeClick = useCallback((node: any) => {
    const n = node as GraphNode;
    if (n.node_type?.toLowerCase() === "community") {
      // Adapt community-typed nodes to the community SelectedEntity shape
      setSelected({
        kind: "community",
        data: {
          community_id: n.community_id ?? n.node_id,
          name: n.name,
          summary: n.description,
          community_level: 0,
          member_count: 0,
          themes: [],
          x: n.x, y: n.y, z: n.z,
        },
      });
    } else {
      setSelected({ kind: "node", data: n });
    }
  }, []);

  const selectedNodeId =
    selected?.kind === "node" ? selected.data.node_id :
    selected?.kind === "community" ? selected.data.community_id : null;

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D) => {
    const color  = nodeColor(node.node_type ?? "unknown");
    const radius = node.node_id === selectedNodeId || node.community_id === selectedNodeId ? 8 : 5;

    // Glow
    ctx.shadowColor = color;
    ctx.shadowBlur  = node === selected ? 24 : 10;

    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    ctx.shadowBlur = 0;
  }, [selected]);

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black">
        <ShaderBackground />
        <Loader2 className="h-8 w-8 animate-spin text-purple-400 relative z-10" />
      </div>
    );
  }

  return (
    <div className="relative h-screen w-full overflow-hidden bg-black">
      <ShaderBackground />

      {/* Stats badge */}
      <div className="absolute bottom-6 left-6 z-10 rounded-xl border border-white/10 bg-black/80 px-3 py-2 backdrop-blur-xl">
        <p className="text-[11px] text-zinc-400">{graphData.nodes.length} nodes · {graphData.links.length} edges</p>
      </div>

      {/* Graph canvas */}
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        nodeId="id"
        nodeLabel={(n: any) => n.name}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => "replace"}
        linkColor={() => "rgba(255,255,255,0.12)"}
        linkWidth={1}
        linkDirectionalParticles={2}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleColor={(l: any) => {
          const src = graphData.nodes.find((n) => n.id === (l.source?.id ?? l.source));
          return src ? nodeColor(src.node_type) : "#ffffff";
        }}
        backgroundColor="rgba(0,0,0,1)"
        d3VelocityDecay={0.3}
        cooldownTicks={120}
        onNodeClick={handleNodeClick}
        onEngineStop={() => {
          if (!fittedRef.current) {
            graphRef.current?.zoomToFit(400, 40);
            fittedRef.current = true;
          }
        }}
      />

      {/* Detail panel — reuses the same component as the 3D graph */}
      <NodeDetailPanel entity={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
