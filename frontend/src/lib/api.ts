import axios from "axios";

const API_BASE_URL = "http://localhost:8000/api/v1";

export const api = {
  async chat(query: string) {
    const response = await axios.post(`${API_BASE_URL}/chat`, { query });
    return response.data;
  },

  async upload(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await axios.post(`${API_BASE_URL}/upload`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  async ingest(data: {
    content: string;
    created_at?: string;
    skip_ingestion?: boolean;
  }) {
    const response = await axios.post(`${API_BASE_URL}/ingest`, data);
    return response.data;
  },

  async getSummary() {
    const response = await axios.get(`${API_BASE_URL}/graph/summary`);
    return response.data;
  },

  async getGraphData() {
    const response = await axios.get(`${API_BASE_URL}/graph/visualization`);
    return response.data;
  },

  async getNotes(search?: string, processed?: boolean, failed?: boolean) {
    const params: any = {};
    if (search) params.search = search;
    if (processed !== undefined) params.processed = processed;
    if (failed !== undefined) params.failed = failed;
    const response = await axios.get(`${API_BASE_URL}/notes`, { params });
    return response.data;
  },

  async getNote(id: string) {
    const response = await axios.get(`${API_BASE_URL}/notes/${id}`);
    return response.data;
  },

  async getNoteStatus(id: string): Promise<{
    id: string;
    processed: boolean;
    failed: boolean;
    status: string;
  }> {
    const response = await axios.get(`${API_BASE_URL}/notes/${id}/status`);
    return response.data;
  },

  async createNote(content: string, created_at?: string) {
    // Create note WITHOUT ingestion (POST /api/v1/notes)
    const response = await axios.post(`${API_BASE_URL}/notes`, {
      content,
      created_at,
    });
    return response.data;
  },

  async updateNote(id: string, content: string, created_at?: string) {
    // Update note WITHOUT re-ingestion
    const response = await axios.put(`${API_BASE_URL}/notes/${id}`, {
      content,
      created_at,
    });
    return response.data;
  },

  async ingestNote(id: string) {
    // Trigger ingestion for an existing note (POST /api/v1/notes/{id}/ingest)
    const response = await axios.post(`${API_BASE_URL}/notes/${id}/ingest`);
    return response.data;
  },

  async deleteNote(id: string) {
    const response = await axios.delete(`${API_BASE_URL}/notes/${id}`);
    return response.data;
  },

  async deleteFile(fileKey: string) {
    const response = await axios.delete(
      `${API_BASE_URL}/files/${encodeURIComponent(fileKey)}`,
    );
    return response.data;
  },

  async submitFeedback(payload: {
    query: string;
    response: string;
    relevance: number;
    quality: number;
    comments?: string;
    node_ids_used?: string[];
  }) {
    const res = await axios.post(`${API_BASE_URL}/feedback`, payload);
    return res.data;
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
    const response = await axios.get(`${API_BASE_URL}/graph/3d/overview`);
    return response.data;
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
    const response = await axios.get(
      `${API_BASE_URL}/graph/3d/community/${communityId}`,
    );
    return response.data;
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
    const response = await axios.get(`${API_BASE_URL}/graph/3d/full`);
    return response.data;
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
    const response = await axios.get(`${API_BASE_URL}/graph/3d/node/${nodeId}`);
    return response.data;
  },
};
