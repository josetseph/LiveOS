import axios from "axios";
import type { NoteStatus } from "@/lib/types";

const API_BASE_URL = "http://localhost:8000/api/v1";

/** Thin wrappers so each method is one line instead of three. */
const http = {
  get: (path: string, params?: Record<string, unknown>) =>
    axios.get(`${API_BASE_URL}${path}`, { params }).then((r) => r.data),
  post: (path: string, data?: unknown) =>
    axios.post(`${API_BASE_URL}${path}`, data).then((r) => r.data),
  put: (path: string, data?: unknown) =>
    axios.put(`${API_BASE_URL}${path}`, data).then((r) => r.data),
  del: (path: string) =>
    axios.delete(`${API_BASE_URL}${path}`).then((r) => r.data),
};

export const api = {
  async chat(query: string) {
    return http.post("/chat", { query });
  },

  async upload(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await axios.post(`${API_BASE_URL}/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  async ingest(data: {
    content: string;
    created_at?: string;
    skip_ingestion?: boolean;
  }) {
    return http.post("/ingest", data);
  },

  async getSummary() {
    return http.get("/graph/summary");
  },

  async getGraphData() {
    return http.get("/graph/visualization");
  },

  async getNotes(search?: string, processed?: boolean, failed?: boolean) {
    const params: Record<string, unknown> = {};
    if (search) params.search = search;
    if (processed !== undefined) params.processed = processed;
    if (failed !== undefined) params.failed = failed;
    return http.get("/notes", params);
  },

  async getNote(id: string) {
    return http.get(`/notes/${id}`);
  },

  async getNoteStatus(id: string): Promise<NoteStatus> {
    return http.get(`/notes/${id}/status`);
  },

  async createNote(content: string, created_at?: string) {
    return http.post("/notes", { content, created_at });
  },

  async updateNote(id: string, content: string, created_at?: string) {
    return http.put(`/notes/${id}`, { content, created_at });
  },

  async ingestNote(id: string) {
    return http.post(`/notes/${id}/ingest`);
  },

  async deleteNote(id: string) {
    return http.del(`/notes/${id}`);
  },

  async deleteFile(fileKey: string) {
    return http.del(`/files/${encodeURIComponent(fileKey)}`);
  },

  async submitFeedback(payload: {
    query: string;
    response: string;
    relevance: number;
    quality: number;
    comments?: string;
    node_ids_used?: string[];
  }) {
    return http.post("/feedback", payload);
  },

  async getHealth() {
    const response = await axios.get("http://localhost:8000/health");
    return response.data;
  },

  // ── 3D Exploration graph ──────────────────────────────────────────────────

  async getGraph3DOverview(): Promise<{
    communities: Array<{
      community_id: string;
      name: string;
      summary: string;
      community_level: number;
      member_count: number;
      themes: string[];
      x: number;
      y: number;
      z: number;
    }>;
    orphan_nodes: Array<{
      node_id: string;
      name: string;
      node_type: string;
      description: string;
      facts: string[];
      x: number;
      y: number;
      z: number;
    }>;
    orphan_edges: Array<{
      source: string;
      target: string;
      type: string;
    }>;
  }> {
    return http.get("/graph/3d/overview");
  },

  async getGraph3DCommunity(communityId: string): Promise<{
    nodes: Array<{
      node_id: string;
      name: string;
      node_type: string;
      description: string;
      facts: string[];
      domain?: string;
      status?: string;
      community_id: string;
      x: number;
      y: number;
      z: number;
    }>;
    edges: Array<{
      source: string;
      target: string;
      type: string;
      natural_language: string;
    }>;
  }> {
    return http.get(`/graph/3d/community/${communityId}`);
  },

  async getGraph3DFull(): Promise<{
    nodes: Array<{
      node_id: string;
      name: string;
      node_type: string;
      description: string;
      facts: string[];
      community_id?: string;
      x: number;
      y: number;
      z: number;
    }>;
    edges: Array<{
      source: string;
      target: string;
      type: string;
    }>;
  }> {
    return http.get("/graph/3d/full");
  },

  async getNodeDetail(nodeId: string): Promise<{
    node_id: string;
    name: string;
    node_type: string;
    description: string;
    isolated_contexts: string[];
    facts: string[];
    domain?: string;
    status?: string;
    community_id?: string;
  }> {
    return http.get(`/graph/3d/node/${nodeId}`);
  },
};
