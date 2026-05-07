export interface CommunityNode {
  community_id: string;
  name: string;
  summary: string;
  community_level: number;
  member_count: number;
  themes: string[];
  x: number;
  y: number;
  z: number;
}

export interface KnowledgeNode {
  node_id: string;
  name: string;
  node_type: string;
  description: string;
  isolated_contexts?: string[];
  facts?: string[];
  domain?: string;
  status?: string;
  community_id?: string;
  x: number;
  y: number;
  z: number;
}

export interface KnowledgeEdge {
  source: string;
  target: string;
  type: string;
  natural_language: string;
}

export interface LoadedCluster {
  communityId: string;
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

/** Flat graph edge returned by /graph/3d/full */
export interface FlatEdge {
  source: string;
  target: string;
  type: string;
}

/** The node that is currently focused in the detail panel */
export type SelectedEntity =
  | { kind: "community"; data: CommunityNode }
  | { kind: "node"; data: KnowledgeNode };
