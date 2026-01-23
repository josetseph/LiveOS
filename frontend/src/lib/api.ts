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

    async ingest(data: { content: string; created_at?: string; skip_ingestion?: boolean }) {
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

    async getNotes(search?: string, processed?: boolean) {
        const params: any = {};
        if (search) params.search = search;
        if (processed !== undefined) params.processed = processed;
        const response = await axios.get(`${API_BASE_URL}/notes`, { params });
        return response.data;
    },

    async getNote(id: string) {
        const response = await axios.get(`${API_BASE_URL}/notes/${id}`);
        return response.data;
    },

    async createNote(content: string, created_at?: string) {
        // Create note WITHOUT ingestion (POST /api/v1/notes)
        const response = await axios.post(`${API_BASE_URL}/notes`, { content, created_at });
        return response.data;
    },

    async updateNote(id: string, content: string, created_at?: string) {
        // Update note WITHOUT re-ingestion  
        const response = await axios.put(`${API_BASE_URL}/notes/${id}`, { content, created_at });
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

    async getHealth() {
        const response = await axios.get("http://localhost:8000/health");
        return response.data;
    }
};
