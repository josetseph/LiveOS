"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import { Stars, Html } from "@react-three/drei";
import * as THREE from "three";
import { api } from "@/lib/api";
import type { KnowledgeNode, FlatEdge } from "./types";
import { nodeColor } from "./nodeColors";

// ── Normalize positions to fit inside a fixed-radius sphere ────────────────────

const TARGET_RADIUS = 30;

function normalizeNodes(nodes: KnowledgeNode[]): KnowledgeNode[] {
  if (nodes.length < 2) return nodes;
  let cx = 0, cy = 0, cz = 0;
  for (const n of nodes) { cx += n.x; cy += n.y; cz += n.z; }
  cx /= nodes.length; cy /= nodes.length; cz /= nodes.length;
  let maxD = 0;
  for (const n of nodes) {
    const d = Math.sqrt((n.x - cx) ** 2 + (n.y - cy) ** 2 + (n.z - cz) ** 2);
    if (d > maxD) maxD = d;
  }
  return nodes.map((n) => {
    const dx = n.x - cx, dy = n.y - cy, dz = n.z - cz;
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    // Power spread (exponent < 1): preserves direction, pushes inner nodes
    // outward so clustered graphs don't all land in the same spot.
    const spread = d > 0 ? (Math.pow(d / maxD, 0.55) * TARGET_RADIUS) / d : 0;
    return { ...n, x: dx * spread, y: dy * spread, z: dz * spread };
  });
}

// ── Colour palette ────────────────────────────────────────────────────────────

// nodeColor is imported from ./nodeColors

// ── Flowing particles along relationship lines ────────────────────────────────

const PARTICLES_PER_EDGE = 4;
const PARTICLE_SPEED = 0.2;

type ParticleState = {
  posArr: Float32Array;
  tArr: Float32Array;
  edgeData: { src: THREE.Vector3; tgt: THREE.Vector3 }[];
  count: number;
  points: THREE.Points;
};

function FlowingParticles({ nodes, edges }: { nodes: KnowledgeNode[]; edges: FlatEdge[] }) {
  const groupRef = useRef<THREE.Group>(null);
  const stateRef = useRef<ParticleState | null>(null);

  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;

    if (stateRef.current) {
      stateRef.current.points.geometry.dispose();
      (stateRef.current.points.material as THREE.Material).dispose();
      group.remove(stateRef.current.points);
      stateRef.current = null;
    }

    const nodeMap = new Map(nodes.map((n) => [n.node_id, n]));
    const edgeData: { src: THREE.Vector3; tgt: THREE.Vector3; color: THREE.Color }[] = [];
    for (const e of edges) {
      const src = nodeMap.get(e.source);
      const tgt = nodeMap.get(e.target);
      if (!src || !tgt) continue;
      edgeData.push({
        src: new THREE.Vector3(src.x, src.y, src.z),
        tgt: new THREE.Vector3(tgt.x, tgt.y, tgt.z),
        color: new THREE.Color(nodeColor(src.node_type)),
      });
    }

    const count = edgeData.length * PARTICLES_PER_EDGE;
    if (count === 0) return;

    const posArr = new Float32Array(count * 3);
    const colArr = new Float32Array(count * 3);
    const tArr = new Float32Array(count);

    let ci = 0;
    for (let ei = 0; ei < edgeData.length; ei++) {
      const { color } = edgeData[ei];
      for (let p = 0; p < PARTICLES_PER_EDGE; p++) {
        tArr[ei * PARTICLES_PER_EDGE + p] = p / PARTICLES_PER_EDGE;
        colArr[ci++] = color.r; colArr[ci++] = color.g; colArr[ci++] = color.b;
      }
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(posArr, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colArr, 3));

    const circleTex = (() => {
      const sz = 64;
      const cv = document.createElement("canvas");
      cv.width = cv.height = sz;
      const ctx = cv.getContext("2d")!;
      ctx.beginPath();
      ctx.arc(sz / 2, sz / 2, sz / 2 - 1, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      return new THREE.CanvasTexture(cv);
    })();

    const mat = new THREE.PointsMaterial({
      size: 0.12,
      map: circleTex,
      alphaMap: circleTex,
      alphaTest: 0.5,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      sizeAttenuation: true,
      depthWrite: false,
    });

    const points = new THREE.Points(geo, mat);
    group.add(points);
    stateRef.current = { posArr, tArr, edgeData, count, points };

    return () => {
      geo.dispose();
      circleTex.dispose();
      mat.dispose();
      group.remove(points);
      stateRef.current = null;
    };
  }, [nodes, edges]);

  useFrame((_, delta) => {
    const s = stateRef.current;
    if (!s) return;
    const { posArr, tArr, edgeData, count, points } = s;

    for (let i = 0; i < count; i++) tArr[i] = (tArr[i] + PARTICLE_SPEED * delta) % 1;

    let pi = 0;
    for (let ei = 0; ei < edgeData.length; ei++) {
      const { src, tgt } = edgeData[ei];
      for (let p = 0; p < PARTICLES_PER_EDGE; p++) {
        const t = tArr[ei * PARTICLES_PER_EDGE + p];
        posArr[pi++] = src.x + (tgt.x - src.x) * t;
        posArr[pi++] = src.y + (tgt.y - src.y) * t;
        posArr[pi++] = src.z + (tgt.z - src.z) * t;
      }
    }

    (points.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
  });

  return <group ref={groupRef} />;
}

// ── Edge lines (single draw call using LineSegments) ─────────────────────────

function EdgeMesh({ nodes, edges }: { nodes: KnowledgeNode[]; edges: FlatEdge[] }) {
  const nodeMap = useMemo(
    () => new Map(nodes.map((n) => [n.node_id, n])),
    [nodes],
  );

  const { geometry, hasColors } = useMemo(() => {
    const pts: THREE.Vector3[] = [];
    const cols: number[] = [];
    for (const e of edges) {
      const src = nodeMap.get(e.source);
      const tgt = nodeMap.get(e.target);
      if (!src || !tgt) continue;
      pts.push(new THREE.Vector3(src.x, src.y, src.z));
      pts.push(new THREE.Vector3(tgt.x, tgt.y, tgt.z));
      const sc = new THREE.Color(nodeColor(src.node_type));
      const tc = new THREE.Color(nodeColor(tgt.node_type));
      cols.push(sc.r, sc.g, sc.b, tc.r, tc.g, tc.b);
    }
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    if (cols.length > 0)
      geo.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
    return { geometry: geo, hasColors: cols.length > 0 };
  }, [edges, nodeMap]);

  if (!hasColors) return null;

  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial vertexColors opacity={0.45} transparent />
    </lineSegments>
  );
}

// ── FPS camera rig: left-drag look, right-drag pan, scroll fly ─────────────────

function CameraRig() {
  const { camera, gl } = useThree();
  // pendingDrag is set on mousedown; dragging activates only after DRAG_THRESHOLD px movement.
  // This prevents a quick node-click from simultaneously triggering a camera drag.
  const pendingDrag = useRef<{ button: number; x: number; y: number } | null>(null);
  const dragging    = useRef(false);
  const rightDrag   = useRef(false);
  const last        = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const canvas = gl.domElement;
    const DRAG_THRESHOLD = 5; // pixels

    const onDown = (e: MouseEvent) => {
      const target = e.target as Element | null;
      if (target && !canvas.contains(target) && target !== canvas) return;
      pendingDrag.current = { button: e.button, x: e.clientX, y: e.clientY };
    };

    const onMove = (e: MouseEvent) => {
      // Activate drag once the pointer has moved past the threshold
      if (pendingDrag.current && !dragging.current) {
        const dx = e.clientX - pendingDrag.current.x;
        const dy = e.clientY - pendingDrag.current.y;
        if (Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) {
          dragging.current  = true;
          rightDrag.current = pendingDrag.current.button === 2;
          last.current      = { x: pendingDrag.current.x, y: pendingDrag.current.y };
          pendingDrag.current = null;
        }
        return;
      }
      if (!dragging.current) return;

      const dx = e.clientX - last.current.x;
      const dy = e.clientY - last.current.y;
      last.current = { x: e.clientX, y: e.clientY };

      if (rightDrag.current) {
        camera.translateX(-dx * 0.04);
        camera.translateY( dy * 0.04);
      } else {
        camera.rotation.order = "YXZ";
        camera.rotation.y -= dx * 0.003;
        camera.rotation.x -= dy * 0.003;
        camera.rotation.x = Math.max(-Math.PI / 2 + 0.01, Math.min(Math.PI / 2 - 0.01, camera.rotation.x));
      }
    };

    const onUp = () => {
      dragging.current    = false;
      pendingDrag.current = null;
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      camera.translateZ(e.deltaY * 0.06);
    };

    const onContextMenu = (e: Event) => e.preventDefault();

    window.addEventListener("mousedown",   onDown);
    window.addEventListener("mousemove",   onMove);
    window.addEventListener("mouseup",     onUp);
    window.addEventListener("wheel",       onWheel, { passive: false });
    canvas.addEventListener("contextmenu", onContextMenu);

    return () => {
      window.removeEventListener("mousedown",   onDown);
      window.removeEventListener("mousemove",   onMove);
      window.removeEventListener("mouseup",     onUp);
      window.removeEventListener("wheel",       onWheel);
      canvas.removeEventListener("contextmenu", onContextMenu);
    };
  }, [camera, gl]);

  return null;
}

// ── NodeLabel: small text label positioned above each cube ──────────────────────
// pointerEvents: none so clicks pass through to the instanced mesh below.

function NodeLabel({ node, isSelected }: { node: KnowledgeNode; isSelected: boolean }) {
  const color = nodeColor(node.node_type);
  return (
    <Html position={[node.x, node.y + 0.42, node.z]} center zIndexRange={[0, 0]}>
      <div
        style={{
          fontSize: 8,
          color: isSelected ? "#fff" : color,
          fontWeight: isSelected ? 700 : 400,
          whiteSpace: "nowrap",
          textShadow: "0 0 6px #000, 0 1px 3px #000",
          fontFamily: "system-ui, sans-serif",
          pointerEvents: "none",
          userSelect: "none",
          letterSpacing: "0.02em",
        }}
      >
        {node.name}
      </div>
    </Html>
  );
}

// ── ProximityLabelLayer: labels only for nodes close to the camera ────────────
// Throttled to LABEL_CHECK_MS ms. Only mounts Html when camera is near.

const LABEL_RADIUS   = 8;    // world units (scene normalised to TARGET_RADIUS=30)
const LABEL_CHECK_MS = 150;
const MAX_LABELS     = 80;

function ProximityLabelLayer({
  nodes,
  selectedId,
}: {
  nodes: KnowledgeNode[];
  selectedId: string | null;
}) {
  const { camera } = useThree();
  const [visibleNodes, setVisibleNodes] = useState<KnowledgeNode[]>([]);
  const lastCheckMs = useRef(0);
  const lastPos     = useRef(new THREE.Vector3());

  useFrame(({ clock }) => {
    const nowMs = clock.getElapsedTime() * 1000;
    if (nowMs - lastCheckMs.current < LABEL_CHECK_MS) return;
    if (camera.position.distanceToSquared(lastPos.current) < 0.01) return;
    lastCheckMs.current = nowMs;
    lastPos.current.copy(camera.position);

    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    const r2 = LABEL_RADIUS * LABEL_RADIUS;
    const nearby: Array<{ node: KnowledgeNode; d2: number }> = [];
    for (const n of nodes) {
      const dx = n.x - cx, dy = n.y - cy, dz = n.z - cz;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < r2) nearby.push({ node: n, d2 });
    }
    nearby.sort((a, b) => a.d2 - b.d2);
    setVisibleNodes(nearby.slice(0, MAX_LABELS).map((x) => x.node));
  });

  return (
    <>
      {visibleNodes.map((node) => (
        <NodeLabel key={node.node_id} node={node} isSelected={node.node_id === selectedId} />
      ))}
    </>
  );
}

// ── AllNodeDots: one Points draw call for all nodes, same style as particles ───
// Circle sprite per node — bright vertex color, sizeAttenuation, clickable.
// index maps directly to nodes[i] for O(1) click → node lookup.

const NODE_CIRCLE_TEX = (() => {
  const sz = 64;
  const cv = document.createElement("canvas");
  cv.width = cv.height = sz;
  const ctx = cv.getContext("2d")!;
  const grad = ctx.createRadialGradient(sz / 2, sz / 2, 0, sz / 2, sz / 2, sz / 2 - 1);
  grad.addColorStop(0,   "rgba(255,255,255,1)");
  grad.addColorStop(0.5, "rgba(255,255,255,0.95)");
  grad.addColorStop(1,   "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(sz / 2, sz / 2, sz / 2 - 1, 0, Math.PI * 2);
  ctx.fill();
  return new THREE.CanvasTexture(cv);
})();

function AllNodeDots({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: KnowledgeNode[];
  selectedId: string | null;
  onSelect: (n: KnowledgeNode) => void;
}) {
  const pointsRef = useRef<THREE.Points>(null);

  // Rebuild geometry only when node list changes
  const geo = useMemo(() => {
    const positions = new Float32Array(nodes.length * 3);
    const colors    = new Float32Array(nodes.length * 3);
    const c = new THREE.Color();
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      positions[i * 3]     = n.x;
      positions[i * 3 + 1] = n.y;
      positions[i * 3 + 2] = n.z;
      c.set(nodeColor(n.node_type));
      colors[i * 3]     = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("color",    new THREE.BufferAttribute(colors.slice(), 3));
    return g;
  }, [nodes]);

  // Patch only the color buffer when selection changes (no geometry rebuild)
  useEffect(() => {
    const colAttr = pointsRef.current?.geometry.attributes.color as THREE.BufferAttribute | undefined;
    if (!colAttr) return;
    const c = new THREE.Color();
    for (let i = 0; i < nodes.length; i++) {
      c.set(nodes[i].node_id === selectedId ? "#ffffff" : nodeColor(nodes[i].node_type));
      colAttr.setXYZ(i, c.r, c.g, c.b);
    }
    colAttr.needsUpdate = true;
  }, [nodes, selectedId]);

  const handleClick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      if (e.index !== undefined) onSelect(nodes[e.index]);
    },
    [nodes, onSelect],
  );

  return (
    <points
      ref={pointsRef}
      geometry={geo}
      onClick={handleClick}
      onPointerOver={() => { document.body.style.cursor = "pointer"; }}
      onPointerOut={() =>  { document.body.style.cursor = "auto";    }}
    >
      <pointsMaterial
        size={0.38}
        map={NODE_CIRCLE_TEX}
        alphaMap={NODE_CIRCLE_TEX}
        alphaTest={0.1}
        vertexColors
        transparent
        opacity={1.0}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

// ── Proximity-based card layer ─────────────────────────────────────────────────
// Only FloatingNode Html cards for the N closest nodes are mounted.
// The camera proximity check runs at most once every CARD_CHECK_MS milliseconds
// and only when the camera has moved more than CARD_MOVE_THRESHOLD units.

const MAX_VISIBLE_CARDS = 25;
const CARD_RADIUS = 9;       // world units (scene is normalised to TARGET_RADIUS=30)
const CARD_CHECK_MS = 150;     // max 6–7 checks/sec
const CARD_MOVE_THRESHOLD2 = 0.04;   // skip check if camera moved < 0.2 units (squared)

function ProximityCardLayer({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: KnowledgeNode[];
  selectedId: string | null;
  onSelect: (n: KnowledgeNode) => void;
}) {
  const { camera } = useThree();
  const [visibleNodes, setVisibleNodes] = useState<KnowledgeNode[]>([]);
  const lastCheckMs = useRef(0);
  const lastCamPos = useRef(new THREE.Vector3());

  useFrame(({ clock }) => {
    const nowMs = clock.getElapsedTime() * 1000;
    if (nowMs - lastCheckMs.current < CARD_CHECK_MS) return;
    if (camera.position.distanceToSquared(lastCamPos.current) < CARD_MOVE_THRESHOLD2) return;

    lastCheckMs.current = nowMs;
    lastCamPos.current.copy(camera.position);

    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    const r2 = CARD_RADIUS * CARD_RADIUS;

    const nearby: Array<{ node: KnowledgeNode; d2: number }> = [];
    for (const n of nodes) {
      const dx = n.x - cx, dy = n.y - cy, dz = n.z - cz;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < r2) nearby.push({ node: n, d2 });
    }
    nearby.sort((a, b) => a.d2 - b.d2);
    setVisibleNodes(nearby.slice(0, MAX_VISIBLE_CARDS).map((x) => x.node));
  });

  return (
    <>
      {visibleNodes.map((node) => (
        <NodeLabel
          key={node.node_id}
          node={node}
          isSelected={node.node_id === selectedId}
        />
      ))}
    </>
  );
}



function SceneContent({
  nodes,
  edges,
  selectedId,
  onSelect,
}: {
  nodes: KnowledgeNode[];
  edges: FlatEdge[];
  selectedId: string | null;
  onSelect: (n: KnowledgeNode) => void;
}) {
  // Normalize once: centers cloud at origin, scales to TARGET_RADIUS
  const normNodes = useMemo(() => normalizeNodes(nodes), [nodes]);

  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[0, 10, 10]} intensity={0.8} />

      {/* Stars fill the far reaches of the scene */}
      <Stars radius={200} depth={60} count={8000} factor={4} saturation={0} fade speed={0.4} />

      {/* FPS camera: left-drag look, right-drag pan, scroll fly */}
      <CameraRig />

      <EdgeMesh nodes={normNodes} edges={edges} />
      <FlowingParticles nodes={normNodes} edges={edges} />

      {/* Circle sprites — one Points draw call for all nodes */}
      <AllNodeDots nodes={normNodes} selectedId={selectedId} onSelect={onSelect} />

      {/* Text labels only for nodes close to the camera */}
      <ProximityLabelLayer nodes={normNodes} selectedId={selectedId} />
    </>
  );
}

// ── Loading indicator ─────────────────────────────────────────────────────────

function LoadingRing() {
  const ref = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.z += dt * 2; });
  return (
    <mesh ref={ref}>
      <torusGeometry args={[1.5, 0.15, 8, 48]} />
      <meshBasicMaterial color="#e879f9" />
    </mesh>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function GraphScene({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (n: KnowledgeNode) => void;
}) {
  const [nodes, setNodes] = useState<KnowledgeNode[]>([]);
  const [edges, setEdges] = useState<FlatEdge[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getGraph3DFull();
        if (!cancelled) {
          setNodes(data.nodes as KnowledgeNode[]);
          setEdges(data.edges as FlatEdge[]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingRing />;

  if (nodes.length === 0) {
    return (
      <>
        <ambientLight intensity={0.6} />
        <Stars radius={200} depth={60} count={8000} factor={4} saturation={0} fade />
        <CameraRig />
      </>
    );
  }

  return (
    <SceneContent
      nodes={nodes}
      edges={edges}
      selectedId={selectedId}
      onSelect={onSelect}
    />
  );
}
