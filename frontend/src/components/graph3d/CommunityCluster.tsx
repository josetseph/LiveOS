"use client";

import { useRef, useState, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Text, Sphere } from "@react-three/drei";
import * as THREE from "three";
import type { CommunityNode, KnowledgeNode, KnowledgeEdge, LoadedCluster, SelectedEntity } from "./types";

// ── Colour palette ───────────────────────────────────────────────────────────

function nodeTypeColor(type: string, domain?: string): string {
  if (type === "community") return "#ffffff";
  if (type === "note") {
    if (domain === "Academic") return "#10b981";
    if (domain === "Professional") return "#a855f7";
    if (domain === "Creative") return "#ec4899";
    if (domain === "Dreams") return "#4338ca";
    return "#3b82f6";
  }
  if (type === "concept") return "#00c6ff";
  if (type === "entity") return "#7000ff";
  if (type === "persona trait") return "#a78bfa";
  if (type === "task") return "#ff0055";
  if (type === "reference") return "#ffd700";
  return "#aaaaaa";
}

// ── Distance thresholds ─────────────────────────────────────────────────────

const SHOW_LABEL_DIST = 500;  // show node name within this many units
const REVEAL_DIST = 400;      // auto-open detail panel within this many units

// ── Individual knowledge node ────────────────────────────────────────────────

export function KnowledgeNodeMesh({
  node,
  cameraPos,
  onSelect,
}: {
  node: KnowledgeNode;
  cameraPos: THREE.Vector3;
  onSelect: (e: SelectedEntity) => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const wasNearRef = useRef(false);
  const color = nodeTypeColor(node.node_type, node.domain);

  // distSq from cameraPos prop — updates whenever SceneContent detects camera moved >2 units
  const distSq = useMemo(() => {
    const dx = node.x - cameraPos.x;
    const dy = node.y - cameraPos.y;
    const dz = node.z - cameraPos.z;
    return dx * dx + dy * dy + dz * dz;
  }, [node.x, node.y, node.z, cameraPos]);

  const showLabel = distSq < SHOW_LABEL_DIST * SHOW_LABEL_DIST;

  useFrame(({ camera }) => {
    if (meshRef.current && hovered) {
      meshRef.current.rotation.y += 0.02;
    }
    // Proximity-based auto-select: fires once on enter, uses live camera pos
    const dx = node.x - camera.position.x;
    const dy = node.y - camera.position.y;
    const dz = node.z - camera.position.z;
    const isNear = dx * dx + dy * dy + dz * dz < REVEAL_DIST * REVEAL_DIST;
    if (isNear && !wasNearRef.current) {
      onSelect({ kind: "node", data: node });
    }
    wasNearRef.current = isNear;
  });

  return (
    <group position={[node.x, node.y, node.z]}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onSelect({ kind: "node", data: node }); }}
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[hovered ? 8 : 6, 16, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={hovered ? 1.4 : 0.7}
          roughness={0.3}
          metalness={0.6}
        />
      </mesh>
      {/* Glow point light on hover */}
      {hovered && <pointLight color={color} intensity={6} distance={60} />}
      {showLabel && (
        <Text
          position={[0, 12, 0]}
          fontSize={8}
          color={color}
          anchorX="center"
          anchorY="bottom"
          maxWidth={120}
          outlineWidth={0.5}
          outlineColor="#000000"
          depthOffset={-1}
        >
          {node.name.length > 28 ? node.name.slice(0, 26) + "…" : node.name}
        </Text>
      )}
    </group>
  );
}

// ── Edges between member nodes ───────────────────────────────────────────────

function EdgeLines({ edges, nodeMap }: { edges: KnowledgeEdge[]; nodeMap: Map<string, KnowledgeNode> }) {
  const points = useMemo(() => {
    const pts: THREE.Vector3[] = [];
    for (const e of edges) {
      const src = nodeMap.get(e.source);
      const tgt = nodeMap.get(e.target);
      if (src && tgt) {
        pts.push(new THREE.Vector3(src.x, src.y, src.z));
        pts.push(new THREE.Vector3(tgt.x, tgt.y, tgt.z));
      }
    }
    return pts;
  }, [edges, nodeMap]);

  if (points.length === 0) return null;

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    return geo;
  }, [points]);

  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#ffffff" opacity={0.12} transparent linewidth={1} />
    </lineSegments>
  );
}

// ── Community cluster sphere (LOD root) ──────────────────────────────────────

const EXPAND_DISTANCE = 300;   // camera enters this radius → load members
const COLLAPSE_DISTANCE = 500; // camera exits this radius → unload members

interface CommunityClusterProps {
  community: CommunityNode;
  cameraPos: THREE.Vector3;
  loadedCluster?: LoadedCluster;
  onRequestLoad: (communityId: string) => void;
  onRequestUnload: (communityId: string) => void;
  onSelect: (e: SelectedEntity) => void;
}

export function CommunityCluster({
  community,
  cameraPos,
  loadedCluster,
  onRequestLoad,
  onRequestUnload,
  onSelect,
}: CommunityClusterProps) {
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  const isExpanded = !!loadedCluster;

  const distSq = useMemo(() => {
    const dx = community.x - cameraPos.x;
    const dy = community.y - cameraPos.y;
    const dz = community.z - cameraPos.z;
    return dx * dx + dy * dy + dz * dz;
  }, [community.x, community.y, community.z, cameraPos]);

  // Expand / collapse based on camera distance
  useFrame(() => {
    if (!isExpanded && distSq < EXPAND_DISTANCE * EXPAND_DISTANCE) {
      onRequestLoad(community.community_id);
    } else if (isExpanded && distSq > COLLAPSE_DISTANCE * COLLAPSE_DISTANCE) {
      onRequestUnload(community.community_id);
    }
    // Slow rotation for community orbs when far
    if (groupRef.current && !isExpanded) {
      groupRef.current.rotation.y += 0.001;
    }
  });

  // Community sphere size scales with member count — large enough to see from a distance
  const sphereRadius = Math.max(25, Math.min(120, 25 + Math.sqrt(community.member_count) * 5));

  const level4Color = "#c084fc"; // purple-ish for level-4 clusters
  const color = level4Color;

  const nodeMap = useMemo(() => {
    if (!loadedCluster) return new Map<string, KnowledgeNode>();
    return new Map(loadedCluster.nodes.map((n) => [n.node_id, n]));
  }, [loadedCluster]);

  const showLabel = distSq < 1500 * 1500;

  return (
    <group ref={groupRef} position={[community.x, community.y, community.z]}>
      {/* Community orb — only visible when members are NOT expanded */}
      {!isExpanded && (
        <>
          <Sphere
            args={[sphereRadius, 24, 24]}
            onClick={(e) => { e.stopPropagation(); onSelect({ kind: "community", data: community }); }}
            onPointerOver={() => setHovered(true)}
            onPointerOut={() => setHovered(false)}
          >
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={hovered ? 0.8 : 0.25}
              transparent
              opacity={hovered ? 0.85 : 0.55}
              roughness={0.4}
              metalness={0.5}
              wireframe={false}
            />
          </Sphere>
          {/* Outer glow shell */}
          <Sphere args={[sphereRadius * 1.35, 16, 16]}>
            <meshStandardMaterial
              color={color}
              emissive={color}
              emissiveIntensity={0.08}
              transparent
              opacity={0.06}
              side={THREE.BackSide}
            />
          </Sphere>
          {hovered && <pointLight color={color} intensity={8} distance={sphereRadius * 4} />}
          {showLabel && (
            <Text
              position={[0, sphereRadius + 6, 0]}
              fontSize={8}
              color={color}
              anchorX="center"
              anchorY="bottom"
              maxWidth={160}
              outlineWidth={0.5}
              outlineColor="#000000"
              depthOffset={-1}
            >
              {community.name.length > 32 ? community.name.slice(0, 30) + "…" : community.name}
            </Text>
          )}
          {showLabel && community.member_count > 0 && (
            <Text
              position={[0, sphereRadius + 1, 0]}
              fontSize={4}
              color="#aaaaaa"
              anchorX="center"
              anchorY="bottom"
              depthOffset={-1}
            >
              {community.member_count} nodes
            </Text>
          )}
        </>
      )}

      {/* Expanded: render member nodes relative to their world positions (already absolute) */}
      {isExpanded && loadedCluster && (
        <group position={[-community.x, -community.y, -community.z]}>
          <EdgeLines edges={loadedCluster.edges} nodeMap={nodeMap} />
          {loadedCluster.nodes.map((n) => (
            <KnowledgeNodeMesh
              key={n.node_id}
              node={n}
              cameraPos={cameraPos}
              onSelect={onSelect}
            />
          ))}
        </group>
      )}
    </group>
  );
}
