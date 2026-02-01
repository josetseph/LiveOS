"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { Loader2, X, Network, Maximize2, Minimize2 } from "lucide-react";
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
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedNode(null);
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
    // Reference nodes (papers, books, citations)
    if (node.group === "Reference") return "#ffd700";
    
    // Community nodes (clusters)
    if (node.group === "Community") return "#ffffff";
    
    // Domain-aware coloring for Notes
    if (node.group === "Note") {
      if (node.domain === "Academic") return "#10b981"; // emerald
      if (node.domain === "Professional") return "#a855f7"; // purple
      if (node.domain === "Creative") return "#ec4899"; // pink/rose
      if (node.domain === "Dreams") return "#4338ca"; // indigo
      return "#3b82f6"; // blue for Personal (default)
    }
    
    // Original colors for other node types
    if (node.group === "Concept") return "#00c6ff";
    if (node.group === "Entity") return "#7000ff";
    if (node.group === "Persona") return "#a78bfa";
    if (node.group === "Task") return "#ff0055";
    return "#ffffff";
  };

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
      <div className="absolute bottom-6 left-6 z-20 max-w-xs rounded-2xl border border-white/10 bg-black/80 p-5 shadow-2xl backdrop-blur-xl transition-all duration-300 hover:scale-[1.02]">
        <div className="mb-4 flex items-center gap-2.5 border-b border-white/10 pb-3">
          <div className="rounded-lg bg-linear-to-br from-purple-500/20 to-purple-500/5 p-2">
            <Network className="h-5 w-5 text-pink-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">Neural Graph</h3>
            <p className="text-[10px] font-medium text-zinc-500">Knowledge Visualization</p>
          </div>
        </div>
        <div className="space-y-2.5">
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-[#00c6ff] shadow-[0_0_12px_#00c6ff]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#00c6ff] opacity-30"></span>
            </div>
            <span className="font-semibold">Concept / Theme</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-[#7000ff] shadow-[0_0_12px_#7000ff]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#7000ff] opacity-30"></span>
            </div>
            <span className="font-semibold">Entity (Person/Place)</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-[#a78bfa] shadow-[0_0_12px_#a78bfa]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#a78bfa] opacity-30"></span>
            </div>
            <span className="font-semibold">Persona / Trait</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-[#ff0055] shadow-[0_0_12px_#ff0055]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#ff0055] opacity-30"></span>
            </div>
            <span className="font-semibold">Task / Goal</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-white shadow-[0_0_12px_rgba(255,255,255,0.6)]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-white opacity-20"></span>
            </div>
            <span className="font-semibold">Note / Memory</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 shrink-0 rounded-full bg-[#ffd700] shadow-[0_0_12px_#ffd700]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#ffd700] opacity-30"></span>
            </div>
            <span className="font-semibold">Reference / Citation</span>
          </div>
        </div>
        <div className="mt-3 space-y-1.5 border-t border-white/10 pt-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Domain Colors</p>
          <div className="flex flex-wrap gap-2">
            <div className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-400">
              Academic
            </div>
            <div className="rounded-md border border-blue-500/20 bg-blue-500/10 px-2 py-1 text-[10px] font-semibold text-blue-400">
              Personal
            </div>
            <div className="rounded-md border border-purple-500/20 bg-purple-500/10 px-2 py-1 text-[10px] font-semibold text-purple-400">
              Professional
            </div>
            <div className="rounded-md border border-pink-500/20 bg-pink-500/10 px-2 py-1 text-[10px] font-semibold text-pink-400">
              Creative
            </div>
            <div className="rounded-md border border-indigo-600/20 bg-indigo-600/10 px-2 py-1 text-[10px] font-semibold text-indigo-400">
              Dreams
            </div>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-center gap-2 border-t border-white/10 pt-3 text-[10px] text-zinc-600">
          <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400"></div>
          <span className="font-mono font-semibold">LIVE GRAPH</span>
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
                  onClick={handleClosePanel}
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
        nodeRelSize={2}
        nodeResolution={20}
        nodeOpacity={0.9}
        cooldownTicks={500}
        warmupTicks={500}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.4}
        d3AlphaMin={0}
        enableNavigationControls={true}
        enablePointerInteraction={true}
        linkColor={() => "rgba(255, 255, 255, 0.2)"}
        linkWidth={0.3}
        linkOpacity={0.3}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={1}
        linkDirectionalParticleSpeed={0.008}
        linkCurvature={0.5}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        linkThreeObjectExtend={true}
        onNodeClick={handleNodeClick}
        enableNodeDrag={false}
        showNavInfo={true}
        backgroundColor="#000000"
        nodeThreeObject={(node: any) => {
          // Only show labels for important nodes (those with many connections)
          const connections = data.links.filter((l: any) => 
            (typeof l.source === 'object' ? l.source.id : l.source) === node.id ||
            (typeof l.target === 'object' ? l.target.id : l.target) === node.id
          ).length;
          
          if (connections < 3) return undefined; // No label for nodes with few connections
          
          const sprite = new SpriteText(node.name, 6);
          // @ts-expect-error - depthWrite exists but not in types
          sprite.material.depthWrite = false;
          sprite.color = getNodeColor(node);
          sprite.textHeight = 1.5;
          // @ts-expect-error - position exists but not in types
          sprite.position.set(0, -4, 0);
          return sprite;
        }}
        nodeThreeObjectExtend={true}
      />
    </div>
  );
}
