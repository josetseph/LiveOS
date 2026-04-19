"use client";

import React, { useEffect, useState, useRef, useCallback, type ReactNode, Component } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { KnowledgeNode } from "@/components/graph3d/types";
import { nodeColor } from "@/components/graph3d/nodeColors";
import * as THREE from "three";

// ForceGraph3D relies on browser APIs — must be dynamically imported (no SSR)
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

// ── Error boundary ────────────────────────────────────────────────────────────

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", background: "#000",
          gap: "1rem", color: "#f87171",
        }}>
          <p style={{ fontSize: "0.9rem", maxWidth: "32rem", textAlign: "center", color: "#94a3b8" }}>
            {this.state.error}
          </p>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: "0.4rem 1rem", background: "rgba(168,85,247,0.2)",
              border: "1px solid rgba(168,85,247,0.5)", borderRadius: "0.4rem",
              color: "#c084fc", cursor: "pointer", fontSize: "0.8rem",
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Node detail modal ─────────────────────────────────────────────────────────

function NodeDetailModal({ node, onClose }: { node: KnowledgeNode; onClose: () => void }) {
  const color = nodeColor(node.node_type);
  const cardRef = useRef<HTMLDivElement>(null);
  const [detail, setDetail] = useState<KnowledgeNode | null>(null);
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setFetching(true);
    api.getNodeDetail(node.node_id)
      .then((d) => { if (!cancelled) setDetail({ ...node, ...d }); })
      .catch(() => { if (!cancelled) setDetail(node); })
      .finally(() => { if (!cancelled) setFetching(false); });
    return () => { cancelled = true; };
  }, [node.node_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const display = detail ?? node;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 999,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(0,0,0,0.78)", backdropFilter: "blur(6px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ position: "relative", maxWidth: 400, width: "100%", margin: "0 1.5rem" }}>
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: -44, right: 0,
            background: "none", border: "none", color: "#fff",
            cursor: "pointer", padding: 4, lineHeight: 1,
          }}
          aria-label="Close"
        >
          <svg width={28} height={28} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>

        <div style={{ width: "100%" }}>
          <div
            ref={cardRef}
            style={{
              borderRadius: 16, background: "#0a0e1a",
              border: `1px solid ${color}55`, padding: "20px 22px",
              boxShadow: `0 0 40px ${color}22, rgba(0,0,0,0.29) 0px 21px 46px`,
              cursor: "default",
            }}
          >
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.12em", color, fontWeight: 700, marginBottom: 8, fontFamily: "system-ui, sans-serif" }}>
              {display.node_type}
            </div>
            <h2 style={{ margin: "0 0 12px", fontSize: 20, fontWeight: 800, color: "#f8fafc", lineHeight: 1.25, fontFamily: "system-ui, sans-serif" }}>
              {display.name}
            </h2>
            {fetching && (
              <div style={{ fontSize: 12, color: "#475569", fontFamily: "system-ui, sans-serif", marginBottom: 8 }}>
                Loading details…
              </div>
            )}
            {display.description && (
              <p style={{ margin: "0 0 12px", fontSize: 13, color: "#94a3b8", lineHeight: 1.6, fontFamily: "system-ui, sans-serif" }}>
                {display.description}
              </p>
            )}
            {display.facts && display.facts.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "#475569", fontWeight: 700, marginBottom: 6, fontFamily: "system-ui, sans-serif" }}>Facts</div>
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {display.facts.slice(0, 5).map((f, i) => (
                    <li key={i} style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 4, lineHeight: 1.5, fontFamily: "system-ui, sans-serif" }}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
            {display.domain && (
              <div style={{ fontSize: 11, color: "#7dd3fc", fontFamily: "system-ui, sans-serif" }}>{display.domain}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── HUD ───────────────────────────────────────────────────────────────────────

function HUD({ nodeCount, edgeCount }: { nodeCount: number; edgeCount: number }) {
  return (
    <>
      <div style={{
        position: "absolute", top: "1.5rem", left: "1.5rem", zIndex: 40,
        background: "rgba(10,10,20,0.75)", border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 12, padding: "0.5rem 1rem",
        color: "#94a3b8", fontSize: "0.75rem", letterSpacing: "0.04em",
        backdropFilter: "blur(8px)", userSelect: "none", pointerEvents: "none",
        fontFamily: "system-ui, sans-serif",
      }}>
        <span style={{ color: "#e879f9", fontWeight: 700 }}>{nodeCount.toLocaleString()}</span>
        <span style={{ margin: "0 0.4em" }}>nodes</span>
        <span style={{ color: "#475569" }}>·</span>
        <span style={{ color: "#22d3ee", fontWeight: 700, marginLeft: "0.4em" }}>{edgeCount.toLocaleString()}</span>
        <span style={{ marginLeft: "0.4em" }}>edges</span>
      </div>
      <div style={{
        position: "absolute", bottom: "1.5rem", left: "50%",
        transform: "translateX(-50%)", zIndex: 40,
        background: "rgba(10,10,20,0.7)", border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: "999px", padding: "0.45rem 1.2rem",
        color: "#94a3b8", fontSize: "0.75rem", letterSpacing: "0.04em",
        backdropFilter: "blur(8px)", userSelect: "none", pointerEvents: "none",
        whiteSpace: "nowrap", fontFamily: "system-ui, sans-serif",
      }}>
        Drag to look &nbsp;·&nbsp; Right drag to pan &nbsp;·&nbsp; Scroll to fly &nbsp;·&nbsp; WASD to move &nbsp;·&nbsp; Click node for details
      </div>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Graph3DPage() {
  const [graphData, setGraphData] = useState<{ nodes: object[]; links: object[] }>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const [proximityLabels, setProximityLabels] = useState<
    Array<{ id: string; name: string; nodeType: string; sx: number; sy: number; opacity: number }>
  >([]);

  // Mirror nodes into a ref so the rAF label loop never has a stale closure
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodesRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);

  // FPS camera rig — all refs so event handlers never stale-close over state
  const pendingDrag = useRef<{ button: number; x: number; y: number } | null>(null);
  const dragging = useRef(false);
  const rightDrag = useRef(false);
  const last = useRef({ x: 0, y: 0 });
  const keysRef = useRef<Set<string>>(new Set());
  const wasdRafRef = useRef<number>(0);
  const rigCleanup = useRef<(() => void) | null>(null);

  useEffect(() => { nodesRef.current = graphData.nodes as any[]; }, [graphData.nodes]); // eslint-disable-line @typescript-eslint/no-explicit-any

  // Build a stable id→node_type map so linkColor can resolve string IDs too
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodeTypeMapRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    const m = new Map<string, string>();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const n of graphData.nodes as any[]) {
      if (n.id != null) m.set(String(n.id), n.node_type ?? "");
    }
    nodeTypeMapRef.current = m;
  }, [graphData.nodes]);

  // ── Proximity labels — show node names when camera is nearby ──────────────
  useEffect(() => {
    if (!graphData.nodes.length) return;

    const PROXIMITY_RADIUS = 400; // world units
    const MAX_LABELS = 12;
    let rafId = 0;
    let lastUpdate = 0;

    const loop = () => {
      rafId = requestAnimationFrame(loop);
      const now = Date.now();
      if (now - lastUpdate < 120) return; // ~8 fps is enough for labels
      lastUpdate = now;

      const fg = graphRef.current;
      if (!fg) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const camera = (fg as any).camera?.();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const renderer = (fg as any).renderer?.();
      if (!camera || !renderer) return;

      const { width, height } = renderer.domElement as HTMLCanvasElement;
      const camPos = camera.position as THREE.Vector3;

      // Find nodes within radius, sorted by distance
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const nearby: Array<{ node: any; dist: number }> = [];
      for (const node of nodesRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const n = node as any;
        const nx = n.fx ?? n.x ?? 0;
        const ny = n.fy ?? n.y ?? 0;
        const nz = n.fz ?? n.z ?? 0;
        const dx = camPos.x - nx;
        const dy = camPos.y - ny;
        const dz = camPos.z - nz;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < PROXIMITY_RADIUS) nearby.push({ node, dist });
      }

      if (!nearby.length) { setProximityLabels([]); return; }

      nearby.sort((a, b) => a.dist - b.dist);
      const top = nearby.slice(0, MAX_LABELS);

      const labels: typeof proximityLabels = [];
      for (const { node, dist } of top) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const n = node as any;
        const nx = n.fx ?? n.x ?? 0;
        const ny = n.fy ?? n.y ?? 0;
        const nz = n.fz ?? n.z ?? 0;

        const vec = new THREE.Vector3(nx, ny, nz);
        vec.project(camera);
        if (vec.z >= 1) continue; // behind clip plane

        const sx = (vec.x + 1) / 2 * width;
        const sy = (1 - vec.y) / 2 * height;
        const opacity = Math.max(0.4, 1 - dist / PROXIMITY_RADIUS);

        labels.push({ id: n.node_id ?? String(n.id), name: n.name ?? "?", nodeType: n.node_type ?? "", sx, sy, opacity });
      }
      setProximityLabels(labels);
    };

    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, [graphData.nodes.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch and adapt data: nodes need `id` field, edges become `links`
  useEffect(() => {
    api.getGraph3DFull()
      .then(({ nodes, edges }) => {
        const nodeIdSet = new Set(nodes.map((n) => n.node_id));
        setGraphData({
          nodes: nodes.map((n) => ({ ...n, id: n.node_id, fx: n.x, fy: n.y, fz: n.z })),
          // Drop edges where either endpoint is missing from the node list
          links: edges
            .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
            .map((e) => ({ source: e.source, target: e.target, type: e.type })),
        });
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Install FPS camera controls once ForceGraph3D is mounted.
  // Poll every 100 ms until graphRef.current exposes camera() + renderer(),
  // then disable built-in OrbitControls and take over with our own listeners.
  useEffect(() => {
    if (!graphData.nodes.length) return;

    const install = () => {
      if (!graphRef.current) return false;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const fg = graphRef.current as any;
      const camera = fg.camera?.();
      const renderer = fg.renderer?.();
      if (!camera || !renderer) return false;

      const controls = fg.controls?.();
      if (controls) controls.enabled = false;

      const canvas = renderer.domElement as HTMLCanvasElement;
      const DRAG_THRESHOLD = 5;

      const onDown = (e: MouseEvent) => {
        pendingDrag.current = { button: e.button, x: e.clientX, y: e.clientY };
      };

      const onMove = (e: MouseEvent) => {
        if (pendingDrag.current && !dragging.current) {
          const dx = e.clientX - pendingDrag.current.x;
          const dy = e.clientY - pendingDrag.current.y;
          if (Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) {
            dragging.current = true;
            rightDrag.current = pendingDrag.current.button === 2;
            last.current = { x: pendingDrag.current.x, y: pendingDrag.current.y };
            pendingDrag.current = null;
          }
          return;
        }
        if (!dragging.current) return;

        const dx = e.clientX - last.current.x;
        const dy = e.clientY - last.current.y;
        last.current = { x: e.clientX, y: e.clientY };

        if (rightDrag.current) {
          // Scale pan speed with camera distance so it feels consistent at any zoom level
          const panSpeed = camera.position.length() * 0.001;
          camera.translateX(-dx * panSpeed);
          camera.translateY(dy * panSpeed);
        } else {
          camera.rotation.order = "YXZ";
          camera.rotation.y -= dx * 0.003;
          camera.rotation.x -= dy * 0.003;
          camera.rotation.x = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, camera.rotation.x));
        }
      };

      const onUp = () => {
        dragging.current = false;
        pendingDrag.current = null;
      };

      const onWheel = (e: WheelEvent) => {
        e.preventDefault();
        camera.translateZ(e.deltaY * 0.35);
      };

      const onContextMenu = (e: Event) => e.preventDefault();

      // WASD fly controls — don't capture when a form element has focus
      const onKeyDown = (e: KeyboardEvent) => {
        const tag = (document.activeElement as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if ((document.activeElement as HTMLElement)?.isContentEditable) return;
        keysRef.current.add(e.key.toLowerCase());
      };
      const onKeyUp = (e: KeyboardEvent) => { keysRef.current.delete(e.key.toLowerCase()); };

      // Smooth WASD loop — speed adapts to camera distance (same feel at any zoom)
      let lastWasdTime = performance.now();
      const wasdLoop = () => {
        wasdRafRef.current = requestAnimationFrame(wasdLoop);
        const now = performance.now();
        const dt = Math.min(now - lastWasdTime, 50);
        lastWasdTime = now;
        const keys = keysRef.current;
        if (!keys.size) return;
        const speed = (camera.position.length() * 0.002 * dt) / 16.67;
        if (keys.has("w")) camera.translateZ(-speed);
        if (keys.has("s")) camera.translateZ(speed);
        if (keys.has("a")) camera.translateX(-speed);
        if (keys.has("d")) camera.translateX(speed);
      };
      wasdRafRef.current = requestAnimationFrame(wasdLoop);

      window.addEventListener("mousedown", onDown);
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      window.addEventListener("wheel", onWheel, { passive: false });
      window.addEventListener("keydown", onKeyDown);
      window.addEventListener("keyup", onKeyUp);
      canvas.addEventListener("contextmenu", onContextMenu);

      rigCleanup.current = () => {
        window.removeEventListener("mousedown", onDown);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        window.removeEventListener("wheel", onWheel);
        window.removeEventListener("keydown", onKeyDown);
        window.removeEventListener("keyup", onKeyUp);
        cancelAnimationFrame(wasdRafRef.current);
        canvas.removeEventListener("contextmenu", onContextMenu);
      };

      return true;
    };

    if (!install()) {
      const id = setInterval(() => { if (install()) clearInterval(id); }, 100);
      return () => {
        clearInterval(id);
        rigCleanup.current?.();
        rigCleanup.current = null;
      };
    }

    return () => {
      rigCleanup.current?.();
      rigCleanup.current = null;
    };
  }, [graphData.nodes.length]);

  const handleNodeClick = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any) => {
      if (dragging.current) return;
      const n: KnowledgeNode = {
        node_id: node.node_id ?? String(node.id ?? ""),
        name: node.name ?? "",
        node_type: node.node_type ?? "unknown",
        description: node.description ?? "",
        facts: node.facts ?? [],
        domain: node.domain,
        status: node.status,
        community_id: node.community_id,
        x: node.x ?? 0,
        y: node.y ?? 0,
        z: node.z ?? 0,
      };
      setSelectedNode(n);
    },
    [],
  );

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "#000", color: "#94a3b8", fontFamily: "system-ui, sans-serif", fontSize: "0.9rem" }}>
        Loading graph…
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100vh", background: "#000" }}>
      <ErrorBoundary>
        <ForceGraph3D
          ref={graphRef}
          graphData={graphData}
          nodeId="id"
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          nodeColor={(node: any) => nodeColor(node.node_type ?? "")}
          nodeRelSize={4}
          nodeOpacity={1.0}
          nodeResolution={16}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          linkColor={(link: any) => {
            const src = link.source;
            const type = typeof src === "object" && src !== null
              ? (src.node_type ?? "")
              : nodeTypeMapRef.current.get(String(src)) ?? "";
            return nodeColor(type);
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          linkDirectionalParticleColor={(link: any) => {
            const src = link.source;
            const type = typeof src === "object" && src !== null
              ? (src.node_type ?? "")
              : nodeTypeMapRef.current.get(String(src)) ?? "";
            return nodeColor(type);
          }}
          linkWidth={1.2}
          linkOpacity={0.5}
          linkCurvature={0.1}
          linkDirectionalParticles={2}
          linkDirectionalParticleWidth={3}
          linkDirectionalParticleSpeed={0.006}
          backgroundColor="#000000"
          showNavInfo={false}
          enableNodeDrag={false}
          enableNavigationControls={false}
          cooldownTicks={0}
          warmupTicks={0}
          onEngineStop={() => {
            // Fit camera to the graph after physics is disabled.
            // zoomToFit works on the Three.js camera directly, so it is
            // compatible with the FPS rig that takes over afterwards.
            graphRef.current?.zoomToFit(400, 600);
          }}
          onNodeClick={handleNodeClick}
        />
      </ErrorBoundary>

      <HUD nodeCount={graphData.nodes.length} edgeCount={graphData.links.length} />

      {/* Proximity labels — appear when camera flies close to a node */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
        {proximityLabels.map((lbl) => (
          <div
            key={lbl.id}
            style={{
              position: "absolute",
              left: lbl.sx,
              top: lbl.sy,
              transform: "translate(-50%, calc(-100% - 10px))",
              color: nodeColor(lbl.nodeType),
              fontSize: "0.72rem",
              fontFamily: "system-ui, sans-serif",
              fontWeight: 600,
              opacity: lbl.opacity,
              textShadow: "0 0 8px #000, 0 0 16px #000, 0 1px 3px #000",
              whiteSpace: "nowrap",
              letterSpacing: "0.03em",
              pointerEvents: "none",
              userSelect: "none",
            }}
          >
            {lbl.name}
          </div>
        ))}
      </div>

      {selectedNode && (
        <NodeDetailModal node={selectedNode} onClose={() => setSelectedNode(null)} />
      )}
    </div>
  );
}
