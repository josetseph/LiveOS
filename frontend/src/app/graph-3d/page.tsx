"use client";

import React, {
  useEffect,
  useState,
  useRef,
  useCallback,
  type ReactNode,
  Component,
} from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { KnowledgeNode } from "@/components/graph3d/types";
import { nodeColor } from "@/components/graph3d/nodeColors";
import * as THREE from "three";

// ForceGraph3D relies on browser APIs — must be dynamically imported (no SSR)
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
});

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
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "#000",
            gap: "1rem",
            color: "#f87171",
          }}
        >
          <p
            style={{
              fontSize: "0.9rem",
              maxWidth: "32rem",
              textAlign: "center",
              color: "#94a3b8",
            }}
          >
            {this.state.error}
          </p>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              padding: "0.4rem 1rem",
              background: "rgba(168,85,247,0.2)",
              border: "1px solid rgba(168,85,247,0.5)",
              borderRadius: "0.4rem",
              color: "#c084fc",
              cursor: "pointer",
              fontSize: "0.8rem",
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

function NodeDetailModal({
  node,
  onClose,
}: {
  node: KnowledgeNode;
  onClose: () => void;
}) {
  const color = nodeColor(node.node_type);
  const cardRef = useRef<HTMLDivElement>(null);
  const [detail, setDetail] = useState<KnowledgeNode | null>(null);
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFetching(true);
    api
      .getNodeDetail(node.node_id)
      .then((d) => {
        if (!cancelled) setDetail({ ...node, ...d });
      })
      .catch(() => {
        if (!cancelled) setDetail(node);
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [node.node_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const display = detail ?? node;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.78)",
        backdropFilter: "blur(6px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          position: "relative",
          maxWidth: 400,
          width: "100%",
          margin: "0 1.5rem",
        }}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: -44,
            right: 0,
            background: "none",
            border: "none",
            color: "#fff",
            cursor: "pointer",
            padding: 4,
            lineHeight: 1,
          }}
          aria-label="Close"
        >
          <svg
            width={28}
            height={28}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
          >
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>

        <div style={{ width: "100%" }}>
          <div
            ref={cardRef}
            style={{
              borderRadius: 16,
              background: "#0a0e1a",
              border: `1px solid ${color}55`,
              padding: "20px 22px",
              boxShadow: `0 0 40px ${color}22, rgba(0,0,0,0.29) 0px 21px 46px`,
              cursor: "default",
            }}
          >
            <div
              style={{
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                color,
                fontWeight: 700,
                marginBottom: 8,
                fontFamily: "system-ui, sans-serif",
              }}
            >
              {display.node_type}
            </div>
            <h2
              style={{
                margin: "0 0 12px",
                fontSize: 20,
                fontWeight: 800,
                color: "#f8fafc",
                lineHeight: 1.25,
                fontFamily: "system-ui, sans-serif",
              }}
            >
              {display.name}
            </h2>
            {fetching && (
              <div
                style={{
                  fontSize: 12,
                  color: "#475569",
                  fontFamily: "system-ui, sans-serif",
                  marginBottom: 8,
                }}
              >
                Loading details…
              </div>
            )}
            {display.description && (
              <p
                style={{
                  margin: "0 0 12px",
                  fontSize: 13,
                  color: "#94a3b8",
                  lineHeight: 1.6,
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                {display.description}
              </p>
            )}
            {display.isolated_contexts && display.isolated_contexts.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div
                  style={{
                    fontSize: 9,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                    color: "#475569",
                    fontWeight: 700,
                    marginBottom: 6,
                    fontFamily: "system-ui, sans-serif",
                  }}
                >
                  Contexts
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {display.isolated_contexts.slice(0, 4).map((ctx, i) => (
                    <div
                      key={i}
                      style={{
                        fontSize: 12,
                        color: "#cbd5e1",
                        lineHeight: 1.55,
                        fontFamily: "system-ui, sans-serif",
                        borderLeft: "2px solid #334155",
                        paddingLeft: 10,
                        fontStyle: "italic",
                      }}
                    >
                      {ctx}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {display.domain && (
              <div
                style={{
                  fontSize: 11,
                  color: "#7dd3fc",
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                {display.domain}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── HUD ───────────────────────────────────────────────────────────────────────

function HUD({
  nodeCount,
  edgeCount,
}: {
  nodeCount: number;
  edgeCount: number;
}) {
  return (
    <>
      <div
        style={{
          position: "absolute",
          top: "1.5rem",
          left: "1.5rem",
          zIndex: 40,
          background: "rgba(10,10,20,0.75)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 12,
          padding: "0.5rem 1rem",
          color: "#94a3b8",
          fontSize: "0.75rem",
          letterSpacing: "0.04em",
          backdropFilter: "blur(8px)",
          userSelect: "none",
          pointerEvents: "none",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <span style={{ color: "#e879f9", fontWeight: 700 }}>
          {nodeCount.toLocaleString()}
        </span>
        <span style={{ margin: "0 0.4em" }}>nodes</span>
        <span style={{ color: "#475569" }}>·</span>
        <span
          style={{ color: "#22d3ee", fontWeight: 700, marginLeft: "0.4em" }}
        >
          {edgeCount.toLocaleString()}
        </span>
        <span style={{ marginLeft: "0.4em" }}>edges</span>
      </div>
      <div
        style={{
          position: "absolute",
          bottom: "1.5rem",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 40,
          background: "rgba(10,10,20,0.7)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: "999px",
          padding: "0.45rem 1.2rem",
          color: "#94a3b8",
          fontSize: "0.75rem",
          letterSpacing: "0.04em",
          backdropFilter: "blur(8px)",
          userSelect: "none",
          pointerEvents: "none",
          whiteSpace: "nowrap",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        Drag to look &nbsp;·&nbsp; Right drag to pan &nbsp;·&nbsp; Scroll to fly
        &nbsp;·&nbsp; WASD to move &nbsp;·&nbsp; Q/E for up/down &nbsp;·&nbsp;
        Click node for details &nbsp;·&nbsp; / to search
      </div>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Graph3DPage() {
  const [graphData, setGraphData] = useState<{
    nodes: object[];
    links: object[];
  }>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [proximityLabels, setProximityLabels] = useState<
    Array<{
      id: string;
      name: string;
      nodeType: string;
      sx: number;
      sy: number;
      opacity: number;
    }>
  >([]);
  const [linkLabels, setLinkLabels] = useState<
    Array<{
      id: string;
      label: string;
      sx: number;
      sy: number;
      opacity: number;
    }>
  >([]);

  // Mirror nodes and links into refs so the rAF label loop never has a stale closure
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodesRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const linksRef = useRef<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<any>(null);

  // FPS camera rig — all refs so event handlers never stale-close over state
  const pendingDrag = useRef<{ button: number; x: number; y: number } | null>(
    null,
  );
  const dragging = useRef(false);
  const rightDrag = useRef(false);
  const last = useRef({ x: 0, y: 0 });
  const keysRef = useRef<Set<string>>(new Set());
  const wasdRafRef = useRef<number>(0);
  const rigCleanup = useRef<(() => void) | null>(null);
  // Quaternion-based look: store yaw/pitch as plain numbers to avoid gimbal lock
  const pitchRef = useRef(0);
  const yawRef = useRef(0);
  const searchOpenRef = useRef(false);
  // Track modal/overlay open state in a ref so camera handlers always see the latest value
  const modalOpenRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchOpenRef.current = searchOpen;
    modalOpenRef.current = selectedNode !== null || searchOpen;
  }, [selectedNode, searchOpen]);

  useEffect(() => {
    nodesRef.current = graphData.nodes as any[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  }, [graphData.nodes]);
  useEffect(() => {
    linksRef.current = graphData.links as any[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  }, [graphData.links]);

  // Build a stable id→node_type map so linkColor can resolve string IDs too
  const nodeTypeMapRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    const m = new Map<string, string>();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const n of graphData.nodes as any[]) {
      if (n.id != null) m.set(String(n.id), n.node_type ?? "");
    }
    nodeTypeMapRef.current = m;
  }, [graphData.nodes]);

  // ── Search results — filter nodes client-side as user types ──
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!searchQuery.trim()) { setSearchResults([]); return; }
    const q = searchQuery.toLowerCase();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const results = (nodesRef.current as any[])
      .filter((n) => (n.name ?? "").toLowerCase().includes(q))
      .sort((a, b) => {
        const aStarts = (a.name ?? "").toLowerCase().startsWith(q);
        const bStarts = (b.name ?? "").toLowerCase().startsWith(q);
        if (aStarts && !bStarts) return -1;
        if (!aStarts && bStarts) return 1;
        return (a.name ?? "").localeCompare(b.name ?? "");
      })
      .slice(0, 8);
    setSearchResults(results);
  }, [searchQuery]);

  // ── Fly camera to a node position (smooth 1.2 s animated approach) ──
  const flyToNode = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const fg = graphRef.current as any;
      if (!fg) return;
      const camera = fg.camera?.();
      if (!camera) return;

      const nx = node.fx ?? node.x ?? 0;
      const ny = node.fy ?? node.y ?? 0;
      const nz = node.fz ?? node.z ?? 0;
      const target = new THREE.Vector3(nx, ny, nz);

      // Approach from current direction, stopping ~80 units away
      const APPROACH_DIST = 80;
      const from = camera.position.clone();
      const dir = from.clone().sub(target);
      const destination =
        dir.length() > APPROACH_DIST
          ? target.clone().add(dir.normalize().multiplyScalar(APPROACH_DIST))
          : from.clone();

      const startPos = from.clone();
      const startTime = performance.now();
      const DURATION = 1200;
      let rafId = 0;

      const loop = () => {
        const t = Math.min((performance.now() - startTime) / DURATION, 1);
        const ease = 1 - Math.pow(1 - t, 3); // cubic ease-out
        camera.position.lerpVectors(startPos, destination, ease);

        // Always look at the target, keeping pitchRef/yawRef in sync
        const lookDir = target.clone().sub(camera.position).normalize();
        pitchRef.current = Math.asin(Math.max(-1, Math.min(1, lookDir.y)));
        yawRef.current = Math.atan2(-lookDir.x, -lookDir.z);
        const euler = new THREE.Euler(pitchRef.current, yawRef.current, 0, "YXZ");
        camera.quaternion.setFromEuler(euler);

        if (t < 1) rafId = requestAnimationFrame(loop);
      };
      rafId = requestAnimationFrame(loop);
      return () => cancelAnimationFrame(rafId);
    },
    [],
  );

  // ── Proximity labels — show node names and relationship labels near camera ──
  useEffect(() => {
    if (!graphData.nodes.length) return;

    const NODE_RADIUS = 400;  // world units for node name labels
    const LINK_RADIUS = 200;  // tighter radius for edge labels
    const MAX_NODE_LABELS = 12;
    const MAX_LINK_LABELS = 8;
    let rafId = 0;
    let lastUpdate = 0;

    // Build a fast id→position lookup so link midpoints can be computed
    // without iterating all nodes every frame
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const posOf = (idOrObj: any): [number, number, number] => {
      // After force-graph resolves links, source/target become object refs
      if (idOrObj && typeof idOrObj === "object") {
        return [idOrObj.fx ?? idOrObj.x ?? 0, idOrObj.fy ?? idOrObj.y ?? 0, idOrObj.fz ?? idOrObj.z ?? 0];
      }
      return [0, 0, 0];
    };

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

      // ── Node labels ─────────────────────────────────────────────────────────
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
        if (dist < NODE_RADIUS) nearby.push({ node, dist });
      }

      if (!nearby.length) {
        setProximityLabels([]);
        setLinkLabels([]);
        return;
      }

      nearby.sort((a, b) => a.dist - b.dist);
      const top = nearby.slice(0, MAX_NODE_LABELS);

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

        const sx = ((vec.x + 1) / 2) * width;
        const sy = ((1 - vec.y) / 2) * height;
        const opacity = Math.max(0.4, 1 - dist / NODE_RADIUS);

        labels.push({
          id: n.node_id ?? String(n.id),
          name: n.name ?? "?",
          nodeType: n.node_type ?? "",
          sx,
          sy,
          opacity,
        });
      }
      setProximityLabels(labels);

      // ── Link labels ─────────────────────────────────────────────────────────
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const nearbyLinks: Array<{ link: any; dist: number }> = [];
      for (const link of linksRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const l = link as any;
        const label: string = (l.type ?? "").replace(/_/g, " ");
        if (!label || label === "MEMBER OF") continue; // skip structural edges
        const [sx, sy, sz] = posOf(l.source);
        const [tx, ty, tz] = posOf(l.target);
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        const mz = (sz + tz) / 2;
        const dx = camPos.x - mx;
        const dy = camPos.y - my;
        const dz = camPos.z - mz;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < LINK_RADIUS) nearbyLinks.push({ link, dist });
      }

      nearbyLinks.sort((a, b) => a.dist - b.dist);
      const topLinks = nearbyLinks.slice(0, MAX_LINK_LABELS);

      const edgeLabels: typeof linkLabels = [];
      for (const { link, dist } of topLinks) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const l = link as any;
        const [sx, sy, sz] = posOf(l.source);
        const [tx, ty, tz] = posOf(l.target);
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        const mz = (sz + tz) / 2;

        const vec = new THREE.Vector3(mx, my, mz);
        vec.project(camera);
        if (vec.z >= 1) continue;

        const screenX = ((vec.x + 1) / 2) * width;
        const screenY = ((1 - vec.y) / 2) * height;
        const opacity = Math.max(0.3, 1 - dist / LINK_RADIUS);
        const linkId = `${String(typeof l.source === "object" ? l.source?.id : l.source)}-${String(typeof l.target === "object" ? l.target?.id : l.target)}-${l.type ?? ""}`;

        edgeLabels.push({
          id: linkId,
          label: (l.type ?? "").replace(/_/g, " "),
          sx: screenX,
          sy: screenY,
          opacity,
        });
      }
      setLinkLabels(edgeLabels);
    };

    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, [graphData.nodes.length, graphData.links.length]);

  // Fetch and adapt data: nodes need `id` field, edges become `links`
  useEffect(() => {
    api
      .getGraph3DFull()
      .then(({ nodes, edges }) => {
        const nodeIdSet = new Set(nodes.map((n) => n.node_id));
        setGraphData({
          nodes: nodes.map((n) => ({
            ...n,
            id: n.node_id,
            fx: n.x,
            fy: n.y,
            fz: n.z,
          })),
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

      // Seed pitch/yaw from the camera's current orientation
      camera.rotation.order = "YXZ";
      pitchRef.current = camera.rotation.x;
      yawRef.current = camera.rotation.y;

      const canvas = renderer.domElement as HTMLCanvasElement;
      const DRAG_THRESHOLD = 5;

      const onDown = (e: MouseEvent) => {
        if (modalOpenRef.current) return;
        pendingDrag.current = { button: e.button, x: e.clientX, y: e.clientY };
      };

      const onMove = (e: MouseEvent) => {
        if (pendingDrag.current && !dragging.current) {
          const dx = e.clientX - pendingDrag.current.x;
          const dy = e.clientY - pendingDrag.current.y;
          if (Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) {
            dragging.current = true;
            rightDrag.current = pendingDrag.current.button === 2;
            last.current = {
              x: pendingDrag.current.x,
              y: pendingDrag.current.y,
            };
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
          // Accumulate yaw and pitch as plain numbers, then compose into a
          // quaternion — avoids gimbal lock so horizontal drag never stops.
          yawRef.current -= dx * 0.003;
          pitchRef.current -= dy * 0.003;
          pitchRef.current = Math.max(
            -Math.PI / 2 + 0.01,
            Math.min(Math.PI / 2 - 0.01, pitchRef.current),
          );
          const euler = new THREE.Euler(pitchRef.current, yawRef.current, 0, "YXZ");
          camera.quaternion.setFromEuler(euler);
        }
      };

      const onUp = () => {
        dragging.current = false;
        pendingDrag.current = null;
      };

      const onWheel = (e: WheelEvent) => {
        if (modalOpenRef.current) return;
        e.preventDefault();
        camera.translateZ(e.deltaY * 0.35);
      };

      const onContextMenu = (e: Event) => e.preventDefault();

      // WASD fly controls — don't capture when a form element has focus or overlay is open
      const onKeyDown = (e: KeyboardEvent) => {
        // Toggle search with / or Ctrl+K / Cmd+K
        if (e.key === "/" && !searchOpenRef.current && !modalOpenRef.current) {
          e.preventDefault();
          setSearchOpen(true);
          return;
        }
        if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          setSearchOpen((v) => !v);
          return;
        }
        if (modalOpenRef.current) return;
        const tag = (document.activeElement as HTMLElement)?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if ((document.activeElement as HTMLElement)?.isContentEditable) return;
        keysRef.current.add(e.key.toLowerCase());
      };
      const onKeyUp = (e: KeyboardEvent) => {
        keysRef.current.delete(e.key.toLowerCase());
      };

      // Smooth WASD loop — speed adapts to camera distance (same feel at any zoom)
      let lastWasdTime = performance.now();
      const wasdLoop = () => {
        wasdRafRef.current = requestAnimationFrame(wasdLoop);
        const now = performance.now();
        const dt = Math.min(now - lastWasdTime, 50);
        lastWasdTime = now;
        if (modalOpenRef.current) { keysRef.current.clear(); return; }
        const keys = keysRef.current;
        if (!keys.size) return;
        const speed = (camera.position.length() * 0.006 * dt) / 16.67;
        if (keys.has("w")) camera.translateZ(-speed);
        if (keys.has("s")) camera.translateZ(speed);
        if (keys.has("a")) camera.translateX(-speed);
        if (keys.has("d")) camera.translateX(speed);
        if (keys.has("q")) camera.position.y += speed;
        if (keys.has("e")) camera.position.y -= speed;
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
      const id = setInterval(() => {
        if (install()) clearInterval(id);
      }, 100);
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          background: "#000",
          color: "#94a3b8",
          fontFamily: "system-ui, sans-serif",
          fontSize: "0.9rem",
        }}
      >
        Loading graph…
      </div>
    );
  }

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100vh",
        background: "#000",
      }}
    >
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
            const type =
              typeof src === "object" && src !== null
                ? (src.node_type ?? "")
                : (nodeTypeMapRef.current.get(String(src)) ?? "");
            return nodeColor(type);
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          linkDirectionalParticleColor={(link: any) => {
            const src = link.source;
            const type =
              typeof src === "object" && src !== null
                ? (src.node_type ?? "")
                : (nodeTypeMapRef.current.get(String(src)) ?? "");
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

      <HUD
        nodeCount={graphData.nodes.length}
        edgeCount={graphData.links.length}
      />

      {/* Proximity labels — appear when camera flies close to a node or edge */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          overflow: "hidden",
        }}
      >
        {proximityLabels.map((lbl) => (
          <div
            key={lbl.id}
            style={{
              position: "absolute",
              left: lbl.sx,
              top: lbl.sy,
              transform: "translate(-50%, calc(-100% - 10px))",
              color: "#ffffff",
              background: "rgba(0,0,0,0.62)",
              border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: "999px",
              padding: "0.15rem 0.5rem",
              fontSize: "0.72rem",
              fontFamily: "system-ui, sans-serif",
              fontWeight: 600,
              opacity: lbl.opacity,
              textShadow: "0 1px 2px #000",
              whiteSpace: "nowrap",
              letterSpacing: "0.03em",
              pointerEvents: "none",
              userSelect: "none",
            }}
          >
            {lbl.name}
          </div>
        ))}
        {linkLabels.map((lbl) => (
          <div
            key={lbl.id}
            style={{
              position: "absolute",
              left: lbl.sx,
              top: lbl.sy,
              transform: "translate(-50%, -50%)",
              color: "rgba(203,213,225,0.9)",
              fontSize: "0.62rem",
              fontFamily: "system-ui, sans-serif",
              fontStyle: "italic",
              fontWeight: 400,
              opacity: lbl.opacity,
              textShadow: "0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.7)",
              whiteSpace: "nowrap",
              letterSpacing: "0.04em",
              pointerEvents: "none",
              userSelect: "none",
            }}
          >
            {lbl.label}
          </div>
        ))}
      </div>

      {/* Search overlay — top-right corner */}
      <div
        style={{
          position: "absolute",
          top: "1.5rem",
          right: "1.5rem",
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
          gap: "0.25rem",
          alignItems: "flex-end",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        {!searchOpen ? (
          <button
            onClick={() => setSearchOpen(true)}
            style={{
              background: "rgba(10,10,20,0.75)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 12,
              padding: "0.45rem 0.9rem",
              color: "#94a3b8",
              fontSize: "0.75rem",
              letterSpacing: "0.04em",
              backdropFilter: "blur(8px)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            Search
            <kbd
              style={{
                background: "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 4,
                padding: "0 0.3rem",
                fontSize: "0.68rem",
                lineHeight: "1.6",
              }}
            >
              /
            </kbd>
          </button>
        ) : (
          <div
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                setSearchOpen(false);
                setSearchQuery("");
              }
            }}
            style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}
          >
            <input
              ref={searchInputRef}
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setSearchOpen(false);
                  setSearchQuery("");
                }
                if (e.key === "Enter" && searchResults.length > 0) {
                  flyToNode(searchResults[0]);
                  setSearchOpen(false);
                  setSearchQuery("");
                }
              }}
              placeholder="Search nodes…"
              style={{
                background: "rgba(10,10,20,0.92)",
                border: "1px solid rgba(255,255,255,0.2)",
                borderRadius: 10,
                padding: "0.5rem 1rem",
                color: "#f1f5f9",
                fontSize: "0.85rem",
                width: 260,
                outline: "none",
                boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
              }}
            />
            {searchResults.length > 0 && (
              <div
                style={{
                  background: "rgba(10,10,20,0.96)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 10,
                  overflow: "hidden",
                  width: 260,
                  boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
                }}
              >
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {searchResults.map((n: any, i: number) => (
                  <button
                    key={n.node_id ?? i}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      flyToNode(n);
                      setSearchOpen(false);
                      setSearchQuery("");
                    }}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      width: "100%",
                      padding: "0.5rem 1rem",
                      border: "none",
                      borderBottom:
                        i < searchResults.length - 1
                          ? "1px solid rgba(255,255,255,0.06)"
                          : "none",
                      background: "transparent",
                      color: "#e2e8f0",
                      fontSize: "0.82rem",
                      cursor: "pointer",
                      textAlign: "left",
                      fontFamily: "system-ui, sans-serif",
                      gap: "0.1rem",
                    }}
                    onMouseEnter={(e) =>
                    (e.currentTarget.style.background =
                      "rgba(255,255,255,0.07)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: nodeColor(n.node_type ?? ""),
                          flexShrink: 0,
                        }}
                      />
                      <span style={{ fontWeight: 600 }}>{n.name}</span>
                    </span>
                    <span style={{ color: "#475569", fontSize: "0.70rem", paddingLeft: "1.2rem" }}>
                      {n.node_type ?? ""}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {selectedNode && (
        <NodeDetailModal
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}
