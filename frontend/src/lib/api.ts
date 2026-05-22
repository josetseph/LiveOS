import axios from "axios";
import type { KnowledgeBase, NoteStatus } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8700/api/v1";

/** Append ?kb=<name> when targeting a non-default knowledge base. */
function kbParam(kb: string): string {
  return kb && kb !== "default" ? `?kb=${encodeURIComponent(kb)}` : "";
}

/** Thin wrappers so each method is one line instead of three. */
const http = {
  get: (path: string, params?: Record<string, unknown>) =>
    axios.get(`${API_BASE_URL}${path}`, { params }).then((r) => r.data),
  post: (path: string, data?: unknown) =>
    axios.post(`${API_BASE_URL}${path}`, data).then((r) => r.data),
  put: (path: string, data?: unknown) =>
    axios.put(`${API_BASE_URL}${path}`, data).then((r) => r.data),
  patch: (path: string, data?: unknown) =>
    axios.patch(`${API_BASE_URL}${path}`, data).then((r) => r.data),
  del: (path: string) =>
    axios.delete(`${API_BASE_URL}${path}`).then((r) => r.data),
};

export const api = {
  // ── Chat ────────────────────────────────────────────────────────────────

  async chat(query: string, kb = "default") {
    return http.post(`/chat${kbParam(kb)}`, { query });
  },

  // ── File storage ─────────────────────────────────────────────────────────

  async upload(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await axios.post(`${API_BASE_URL}/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },

  async deleteFile(fileKey: string) {
    return http.del(`/files/${encodeURIComponent(fileKey)}`);
  },

  // ── Notes (Postgres — not KB-scoped except ingest/delete) ───────────────

  async ingest(data: {
    content: string;
    created_at?: string;
    skip_ingestion?: boolean;
  }, kb = "default") {
    return http.post(`/ingest${kbParam(kb)}`, data);
  },

  async getNotes(search?: string, processed?: boolean, failed?: boolean, kb = "default") {
    const params: Record<string, unknown> = {};
    if (search) params.search = search;
    if (processed !== undefined) params.processed = processed;
    if (failed !== undefined) params.failed = failed;
    return http.get(`/notes${kbParam(kb)}`, params);
  },

  async getNote(id: string) {
    return http.get(`/notes/${id}`);
  },

  async getNoteStatus(id: string): Promise<NoteStatus> {
    return http.get(`/notes/${id}/status`);
  },

  async createNote(content: string, created_at?: string, kb = "default") {
    return http.post(`/notes${kbParam(kb)}`, { content, created_at });
  },

  async updateNote(id: string, content: string, created_at?: string) {
    return http.put(`/notes/${id}`, { content, created_at });
  },

  /** Ingest an existing note into the given KB (default KB if omitted). */
  async ingestNote(id: string, kb = "default") {
    return http.post(`/notes/${id}/ingest${kbParam(kb)}`);
  },

  /** Delete note from Postgres and from the given KB's graph. */
  async deleteNote(id: string, kb = "default") {
    return http.del(`/notes/${id}${kbParam(kb)}`);
  },

  // ── Graph summary ─────────────────────────────────────────────────────────

  async getSummary(kb = "default") {
    return http.get(`/graph/summary${kbParam(kb)}`);
  },

  async getGraphData(kb = "default") {
    return http.get(`/graph/visualization${kbParam(kb)}`);
  },

  // ── Feedback ──────────────────────────────────────────────────────────────

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

  // ── Health ───────────────────────────────────────────────────────────────

  async getHealth() {
    const response = await axios.get(`${API_BASE_URL.replace("/api/v1", "")}/health`);
    return response.data;
  },

  // ── 3D Exploration graph ──────────────────────────────────────────────────

  async getGraph3DOverview(kb = "default"): Promise<{
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
    return http.get(`/graph/3d/overview${kbParam(kb)}`);
  },

  async getGraph3DCommunity(communityId: string, kb = "default"): Promise<{
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
    return http.get(`/graph/3d/community/${communityId}${kbParam(kb)}`);
  },

  async getGraph3DFull(kb = "default"): Promise<{
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
    return http.get(`/graph/3d/full${kbParam(kb)}`);
  },

  async getNodeDetail(nodeId: string, kb = "default"): Promise<{
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
    return http.get(`/graph/3d/node/${nodeId}${kbParam(kb)}`);
  },

  // ── Entity mention autocomplete ───────────────────────────────────────────

  async searchEntities(
    q: string,
    kb = "default",
    limit = 5,
  ): Promise<{ node_id: string; name: string; node_type: string }[]> {
    const params: Record<string, unknown> = { q, limit };
    if (kb && kb !== "default") params.kb = kb;
    return http.get("/graph/entities/search", params);
  },

  async scanTextEntities(
    text: string,
    kb = "default",
  ): Promise<{ node_id: string; name: string; node_type: string }[]> {
    const params: Record<string, unknown> = {};
    if (kb && kb !== "default") params.kb = kb;
    return http.post(`/graph/entities/scan-text${kbParam(kb)}`, { text });
  },

  // ── Knowledge-base management ─────────────────────────────────────────────

  async listKBs(): Promise<{ knowledge_bases: KnowledgeBase[] }> {
    return http.get("/kb");
  },

  async createKB(name: string): Promise<{ id: string; name: string; message: string }> {
    return http.post("/kb", { name });
  },

  async renameKB(id: string, name: string): Promise<{ id: string; name: string }> {
    return http.patch(`/kb/${id}`, { name });
  },

  async deleteKB(id: string): Promise<void> {
    return http.del(`/kb/${id}`);
  },

  // ── LLM runtime settings ──────────────────────────────────────────────────

  async getLLMSettings(): Promise<{ provider: string; model: string; ingestion_model: string; base_url: string }> {
    return http.get("/settings");
  },

  async updateLLMSettings(data: {
    provider?: string;
    model?: string;
    ingestion_model?: string;
    base_url?: string;
  }): Promise<{ provider: string; model: string; ingestion_model: string; base_url: string }> {
    return http.patch("/settings", data);
  },
};
