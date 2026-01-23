"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { Loader2, X, Info, Network, Maximize2, Minimize2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import SpriteText from "three-spritetext";

// Dynamically import ForceGraph3D as it relies on window/browser APIs
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
});

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

interface Node {
  id: number;
  name: string;
  group: string;
  summary?: string;
  description?: string;
  trait?: string;
  status?: string;
  entity_type?: string;
  created_at?: string;
  x?: number;
  y?: number;
  z?: number;
}

interface Link {
  source: number | Node;
  target: number | Node;
  type: string;
  created_at?: string;
}

interface GraphData {
  nodes: Node[];
  links: Link[];
}

export default function Graph3DPage() {
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/graph/export`);
        const graphData = await response.json();
        setData(graphData);
      } catch (error) {
        console.error("Failed to fetch graph data", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    
    // Zoom to node
    if (graphRef.current) {
      const distance = 400;
      const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
      
      graphRef.current.cameraPosition(
        { 
          x: (node.x || 0) * distRatio, 
          y: (node.y || 0) * distRatio, 
          z: (node.z || 0) * distRatio 
        },
        node, // lookAt
        3000 // ms transition
      );
    }
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  }, []);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  // Node color based on group type
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const getNodeColor = (node: any) => {
    const colors: Record<string, string> = {
      Concept: "#00c6ff",
      Entity: "#7000ff",
      Task: "#a78bfa",
      Persona: "#ec4899",
      Reference: "#10b981",
      Note: "#64748b",
    };
    return colors[node.group] || "#ffffff";
  };

  // Link color - subtle gradient
  const getLinkColor = () => "#ffffff20";

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black">
        <Loader2 className="h-8 w-8 animate-spin text-purple-400" />
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative h-screen w-full overflow-hidden bg-black">

      {/* Top Controls */}
      <div className="absolute top-6 left-6 z-20 flex items-center gap-4">
        <div className="rounded-2xl border border-white/10 bg-black/80 px-6 py-3 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-linear-to-br from-purple-500/20 to-purple-500/5 p-2">
              <Network className="h-5 w-5 text-pink-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">3D Knowledge Graph</h1>
              <p className="text-xs text-zinc-500">
                {data.nodes.length} nodes · {data.links.length} connections
              </p>
            </div>
          </div>
        </div>

        <button
          onClick={toggleFullscreen}
          className="rounded-xl border border-white/10 bg-black/80 p-3 backdrop-blur-xl transition-all hover:bg-white/5 hover:scale-105"
        >
          {isFullscreen ? (
            <Minimize2 className="h-5 w-5 text-purple-400" />
          ) : (
            <Maximize2 className="h-5 w-5 text-purple-400" />
          )}
        </button>
      </div>

      {/* Legend */}
      <div className="absolute bottom-6 left-6 z-20 max-w-xs rounded-2xl border border-white/10 bg-black/80 p-5 shadow-2xl backdrop-blur-xl">
        <div className="mb-4 flex items-center gap-2.5 border-b border-white/10 pb-3">
          <Info className="h-5 w-5 text-pink-400" />
          <h3 className="text-sm font-bold text-white">Node Types</h3>
        </div>
        <div className="space-y-2">
          {[
            { label: "Concept", color: "#00c6ff" },
            { label: "Entity", color: "#7000ff" },
            { label: "Task", color: "#a78bfa" },
            { label: "Persona", color: "#ec4899" },
            { label: "Reference", color: "#10b981" },
            { label: "Note", color: "#64748b" },
          ].map(({ label, color }) => (
            <div key={label} className="flex items-center gap-3 text-sm text-zinc-300">
              <span
                className="block h-3 w-3 rounded-full shadow-lg"
                style={{ backgroundColor: color, boxShadow: `0 0 12px ${color}` }}
              ></span>
              <span className="font-medium">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Node Details Panel */}
      <AnimatePresence>
        {selectedNode && (
          <motion.div
            initial={{ opacity: 0, x: 400 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 400 }}
            className="absolute top-6 right-6 z-20 w-96 rounded-2xl border border-white/10 bg-black/90 shadow-2xl backdrop-blur-xl"
          >
            <div className="p-6">
              <div className="mb-4 flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span
                    className="block h-4 w-4 rounded-full shadow-lg"
                    style={{
                      backgroundColor: getNodeColor(selectedNode),
                      boxShadow: `0 0 12px ${getNodeColor(selectedNode)}`,
                    }}
                  ></span>
                  <div>
                    <h2 className="text-lg font-bold text-white">{selectedNode.name}</h2>
                    <p className="text-xs text-zinc-500">{selectedNode.group}</p>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
                  title="Close panel"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-3">
                {selectedNode.summary && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Summary
                    </p>
                    <p className="text-sm text-zinc-300 leading-relaxed">{selectedNode.summary}</p>
                  </div>
                )}

                {selectedNode.description && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Description
                    </p>
                    <p className="text-sm text-zinc-300 leading-relaxed">
                      {selectedNode.description}
                    </p>
                  </div>
                )}

                {selectedNode.trait && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Trait
                    </p>
                    <p className="text-sm text-zinc-300 leading-relaxed">{selectedNode.trait}</p>
                  </div>
                )}

                {selectedNode.status && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Status
                    </p>
                    <p className="text-sm text-zinc-300">{selectedNode.status}</p>
                  </div>
                )}

                {selectedNode.entity_type && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Type
                    </p>
                    <p className="text-sm text-zinc-300">{selectedNode.entity_type}</p>
                  </div>
                )}

                {selectedNode.created_at && (
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-1">
                      Created
                    </p>
                    <p className="text-sm text-zinc-300">
                      {new Date(selectedNode.created_at).toLocaleDateString()}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 3D Force Graph */}
      <ForceGraph3D
        ref={graphRef}
        graphData={data}
        nodeLabel="name"
        nodeAutoColorBy="group"
        nodeColor={getNodeColor}
        nodeRelSize={3}
        nodeResolution={16}
        nodeOpacity={0.9}
        linkColor={(link: any) => getNodeColor(link.source)}
        linkWidth={0.5}
        linkOpacity={0.6}
        linkDirectionalParticles={4}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleSpeed={0.008}
        linkCurvature={0.2}
        linkDirectionalArrowLength={6}
        linkDirectionalArrowRelPos={1}
        onNodeClick={handleNodeClick}
        enableNodeDrag={true}
        enableNavigationControls={true}
        showNavInfo={false}
        backgroundColor="#000000"
        nodeThreeObject={(node: any) => {
          const sprite = new SpriteText(node.name, 8);
          // @ts-expect-error - depthWrite exists but not in types
          sprite.material.depthWrite = false;
          sprite.color = getNodeColor(node);
          sprite.textHeight = 5;
          sprite.center.set(0, -1.5, 0); // Position text below node
          return sprite;
        }}
        nodeThreeObjectExtend={true}
      />
    </div>
  );
}
