"use client";

import React, { useEffect, useState, useRef } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { Loader2, X, FileText, Info, Network, Calendar } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { ShaderBackground } from "@/components/shader-background";

// Dynamically import ForceGraph2D as it relies on window/browser APIs
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

export default function GraphPage() {
  const [data, setData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [nodeDetails, setNodeDetails] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const graphRef = useRef<any>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const graphData = await api.getGraphData();
        setData(graphData);
      } catch (error) {
        console.error("Failed to fetch graph data", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleNodeClick = async (node: any) => {
    setSelectedNode(node);
    setNodeDetails(null);

    // Focus camera on node
    graphRef.current?.centerAt(node.x, node.y, 1000);
    graphRef.current?.zoom(4, 1000);

    if (node.group === "Note" && node.uuid) {
      setDetailLoading(true);
      try {
        const details = await api.getNote(node.uuid);
        setNodeDetails(details);
      } catch (error) {
        console.error("Failed to fetch note details", error);
      } finally {
        setDetailLoading(false);
      }
    }
  };

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
      {/* Legend */}
      <div className="absolute bottom-6 left-6 z-10 max-w-xs rounded-2xl border border-white/10 bg-black/80 p-5 shadow-2xl backdrop-blur-xl transition-all duration-300 hover:scale-[1.02]">
        <div className="mb-4 flex items-center gap-2.5 border-b border-white/10 pb-3">
          <div className="rounded-lg bg-gradient-to-br from-purple-500/20 to-purple-500/5 p-2">
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
              <span className="block h-3.5 w-3.5 flex-shrink-0 rounded-full bg-[#00c6ff] shadow-[0_0_12px_#00c6ff]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#00c6ff] opacity-30"></span>
            </div>
            <span className="font-semibold">Concept / Theme</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 flex-shrink-0 rounded-full bg-[#7000ff] shadow-[0_0_12px_#7000ff]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#7000ff] opacity-30"></span>
            </div>
            <span className="font-semibold">Entity (Person/Place)</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 flex-shrink-0 rounded-full bg-[#ffbd2e] shadow-[0_0_12px_#ffbd2e]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#ffbd2e] opacity-30"></span>
            </div>
            <span className="font-semibold">Persona / Trait</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 flex-shrink-0 rounded-full bg-[#ff0055] shadow-[0_0_12px_#ff0055]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-[#ff0055] opacity-30"></span>
            </div>
            <span className="font-semibold">Task / Goal</span>
          </div>
          <div className="group flex cursor-default items-center gap-3 rounded-lg border border-transparent p-2 text-sm text-zinc-300 transition-all hover:border-white/10 hover:bg-white/5">
            <div className="relative">
              <span className="block h-3.5 w-3.5 flex-shrink-0 rounded-full bg-white shadow-[0_0_12px_rgba(255,255,255,0.6)]"></span>
              <span className="absolute inset-0 h-3.5 w-3.5 animate-ping rounded-full bg-white opacity-20"></span>
            </div>
            <span className="font-semibold">Note / Memory</span>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-center gap-2 border-t border-white/10 pt-3 text-[10px] text-zinc-600">
          <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400"></div>
          <span className="font-mono font-semibold">LIVE GRAPH</span>
        </div>
      </div>

      {/* Graph */}
      <ForceGraph2D
        ref={graphRef}
        graphData={data}
        nodeLabel={(node: any) => node.title || node.name}
        nodeColor={(node: any) => {
          if (node.group === "Concept") return "#00c6ff";
          if (node.group === "Entity") return "#7000ff";
          if (node.group === "Persona") return "#ffbd2e";
          if (node.group === "Task") return "#ff0055";
          if (node.group === "Note") return "#ffffff";
          return "#ffffff";
        }}
        nodeRelSize={6}
        linkColor={() => "rgba(255,255,255,0.15)"}
        backgroundColor="rgba(0,0,0,1)"
        d3VelocityDecay={0.3}
        cooldownTicks={100}
        onNodeClick={handleNodeClick}
        onEngineStop={() => graphRef.current?.zoomToFit(400)}
      />

      {/* Node Detail Panel */}
      <AnimatePresence>
        {selectedNode && (
          <motion.div
            initial={{ x: 400, opacity: 0, scale: 0.95 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: 400, opacity: 0, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 200, damping: 25 }}
            className="absolute bottom-6 right-6 top-6 z-20 flex w-[420px] flex-col rounded-2xl border border-white/10 bg-black/80 p-6 shadow-2xl backdrop-blur-xl"
          >
            <div className="mb-5 flex items-center justify-between border-b border-white/10 pb-4">
              <div className="flex items-center gap-2.5">
                <div
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-xs font-bold uppercase tracking-wider",
                    selectedNode.group === "Concept" &&
                      "border-[#00c6ff]/30 bg-[#00c6ff]/15 text-[#00c6ff] shadow-lg shadow-[#00c6ff]/10",
                    selectedNode.group === "Entity" &&
                      "border-[#7000ff]/30 bg-[#7000ff]/15 text-[#7000ff] shadow-lg shadow-[#7000ff]/10",
                    selectedNode.group === "Persona" &&
                      "border-[#ffbd2e]/30 bg-[#ffbd2e]/15 text-[#ffbd2e] shadow-lg shadow-[#ffbd2e]/10",
                    selectedNode.group === "Task" &&
                      "border-[#ff0055]/30 bg-[#ff0055]/15 text-[#ff0055] shadow-lg shadow-[#ff0055]/10",
                    selectedNode.group === "Note" && "border-white/20 bg-white/10 text-white"
                  )}
                >
                  {selectedNode.group}
                </div>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="group rounded-xl border border-white/5 p-2 text-zinc-400 transition-all hover:border-white/10 hover:bg-white/5 hover:text-white"
              >
                <X className="h-5 w-5 transition-transform duration-300 group-hover:rotate-90" />
              </button>
            </div>

            <h2 className="mb-3 text-2xl font-bold leading-tight text-white">
              {selectedNode.title || selectedNode.name}
            </h2>

            {selectedNode.created_at && (
              <div className="mb-5 w-fit rounded-lg border border-white/5 bg-white/5 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                  <span className="text-xs font-medium text-zinc-400">
                    {new Date(selectedNode.created_at).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </span>
                </div>
              </div>
            )}

            <div className="flex-1 space-y-4 overflow-y-auto pr-2">
              {detailLoading ? (
                <div className="flex flex-col items-center justify-center gap-3 py-12">
                  <div className="rounded-xl bg-white/5 p-3">
                    <Loader2 className="h-6 w-6 animate-spin text-purple-400" />
                  </div>
                  <span className="text-xs font-medium text-zinc-500">Loading details...</span>
                </div>
              ) : (
                <>
                  {selectedNode.group === "Note" && nodeDetails ? (
                    <div className="rounded-xl border border-white/10 bg-white/5 p-5">
                      <div className="mb-3 flex items-center gap-2 border-b border-white/10 pb-3">
                        <FileText className="h-4 w-4 text-pink-400" />
                        <span className="text-xs font-bold uppercase tracking-wider text-white">
                          Full Content
                        </span>
                      </div>
                      <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-p:text-zinc-300">
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
                          {nodeDetails.content}
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="rounded-xl border border-white/10 bg-white/5 p-5">
                        <div className="mb-3 flex items-center gap-2">
                          <Info className="h-4 w-4 text-pink-400" />
                          <span className="text-xs font-bold uppercase tracking-wider text-white">Summary</span>
                        </div>
                        <p className="text-sm leading-relaxed text-zinc-300">
                          {selectedNode.summary ||
                            (selectedNode.group === "Concept"
                              ? "This is a key theme identified in your knowledge base."
                              : "This entity is connected to your notes and thoughts.")}
                        </p>
                      </div>
                      <div className="rounded-xl border border-white/5 bg-white/5 p-4 text-center">
                        <p className="text-xs font-medium text-zinc-500">
                          Click Notes in the sidebar to create new connections
                        </p>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
