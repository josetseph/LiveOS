import axios from "axios";
import type { ChatConversation, ChatMessageRecord, ChatStatus, KnowledgeBase, NoteStatus } from "@/lib/types";
import { resolveApiBaseUrl } from "@/lib/desktop";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api/v1").replace(/\/$/, "");
const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1$/, "");

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

  async chat(query: string, kb = "default", requestId?: string) {
    return http.post(`/chat${kbParam(kb)}`, { query, request_id: requestId });
  },

  async startChat(
    query: string,
    kb = "default",
    requestId?: string,
    conversationId?: string | null,
  ) {
    return http.post(`/chat/async${kbParam(kb)}`, {
      query,
      request_id: requestId,
      conversation_id: conversationId || undefined,
    });
  },

  async getChatStatus(requestId: string): Promise<ChatStatus> {
    return http.get(`/chat/status/${requestId}`);
  },

  async listChatConversations(kb = "default"): Promise<ChatConversation[]> {
    return http.get(`/chat/conversations${kbParam(kb)}`);
  },

  async createChatConversation(kb = "default", title?: string) {
    return http.post(`/chat/conversations${kbParam(kb)}`, title ? { title } : {});
  },

  async getChatMessages(conversationId: string): Promise<ChatMessageRecord[]> {
    return http.get(`/chat/conversations/${conversationId}/messages`);
  },

  async deleteChatConversation(conversationId: string) {
    return http.del(`/chat/conversations/${conversationId}`);
  },

  // ── File storage ─────────────────────────────────────────────────────────

  async upload(file: File, kb = "default") {
    const formData = new FormData();
    formData.append("file", file);
    // Desktop: hit FastAPI directly so large files aren't truncated by the
    // Next.js rewrite proxy (default 10MB → socket hang up / 500).
    const base = await resolveApiBaseUrl(API_BASE_URL);
    const response = await axios.post(
      `${base}/upload${kbParam(kb)}`,
      formData,
      { timeout: 10 * 60 * 1000 },
    );
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

  async getNote(id: string, kb = "default") {
    return http.get(`/notes/${id}${kbParam(kb)}`);
  },

  async getNoteStatus(id: string): Promise<NoteStatus> {
    return http.get(`/notes/${id}/status`);
  },

  async createNote(
    content: string,
    created_at?: string,
    kb = "default",
    title?: string,
    folder?: string,
  ) {
    return http.post(`/notes${kbParam(kb)}`, {
      content,
      created_at,
      title,
      folder: folder || undefined,
    });
  },

  async moveNote(id: string, folder: string, kb = "default") {
    return http.post(`/notes/${id}/move${kbParam(kb)}`, { folder });
  },

  async moveVaultFile(fromRel: string, toRel: string, kb = "default") {
    return http.post(`/vault/move${kbParam(kb)}`, {
      from_rel: fromRel,
      to_rel: toRel,
    });
  },

  async deleteVaultFile(relPath: string, kb = "default") {
    return http.post(`/vault/delete${kbParam(kb)}`, { rel_path: relPath });
  },

  async listVaultFolders(kb = "default"): Promise<{
    folders: string[];
    attachments?: Array<{ name: string; rel_path: string }>;
    media_files?: Array<{ name: string; rel_path: string }>;
    vault_name?: string;
    vault_path?: string;
  }> {
    return http.get(`/vault/folders${kbParam(kb)}`);
  },

  async mkdirVaultFolder(path: string, kb = "default") {
    return http.post(`/vault/mkdir${kbParam(kb)}`, { path });
  },

  async resolveVaultLocalPath(relOrUrl: string, kb = "default"): Promise<{
    rel_path: string;
    local_path: string;
    vault_path: string;
    exists: boolean;
  }> {
    return http.get(`/vault/local-path${kbParam(kb)}`, { rel: relOrUrl });
  },

  async updateNote(
    id: string,
    content: string,
    created_at?: string,
    kb = "default",
    title?: string,
  ) {
    return http.put(`/notes/${id}${kbParam(kb)}`, { content, created_at, title });
  },

  /** Ingest an existing note into the given KB (default KB if omitted). */
  async ingestNote(id: string, kb = "default") {
    return http.post(`/notes/${id}/ingest${kbParam(kb)}`);
  },

  /** Delete note from Postgres and from the given KB's graph. */
  async deleteNote(id: string, kb = "default") {
    return http.del(`/notes/${id}${kbParam(kb)}`);
  },

  /** Batch-delete notes (vault + SQLite + graph cleanup). Max 100. */
  async batchDeleteNotes(
    ids: string[],
    kb = "default",
  ): Promise<{
    deleted: string[];
    failed: Array<{ id: string; error: string }>;
    deleted_count: number;
    failed_count: number;
  }> {
    return http.post(`/notes/batch-delete${kbParam(kb)}`, { ids });
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
    const response = await axios.get(`${API_ORIGIN}/health`);
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
    community_name?: string;
    connections?: {
      node_id: string;
      name: string;
      kind?: string;
      relationship?: string;
      direction?: string;
    }[];
    related_notes?: { note_id: string; name: string }[];
  }> {
    return http.get(
      `/graph/3d/node/${encodeURIComponent(nodeId)}${kbParam(kb)}`,
    );
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

  async createKB(
    name: string,
    vaultPath?: string,
  ): Promise<{ id: string; name: string; vault_path?: string; message: string }> {
    return http.post("/kb", { name, vault_path: vaultPath || undefined });
  },

  async renameKB(id: string, name: string): Promise<{ id: string; name: string }> {
    return http.patch(`/kb/${id}`, { name });
  },

  async deleteKB(id: string): Promise<void> {
    return http.del(`/kb/${id}`);
  },

  async emptyKB(kb = "default"): Promise<{
    status: string;
    kb_id: string;
    name: string;
    notes_removed: number;
    vault_path: string;
    message: string;
  }> {
    return http.post(`/kb/empty${kbParam(kb)}`, {});
  },

  async deleteAllNonDefaultKBs(): Promise<{
    removed: Array<{ id: string; name?: string; vault_path?: string }>;
    errors: Array<{ id: string; error: string }>;
    removed_count: number;
    message: string;
  }> {
    return http.post(`/kb/delete-non-default`, {});
  },

  // ── Setup / paths ─────────────────────────────────────────────────────────

  async getSetupStatus(): Promise<import("@/lib/types").SetupStatus> {
    return http.get("/setup/status");
  },

  async getModelCatalog(chatId?: string) {
    return http.get("/setup/model-catalog", chatId ? { chat_id: chatId } : undefined);
  },

  async saveSetupPaths(data: {
    data_dir: string;
    models_dir: string;
    default_vault_path?: string;
    ai_setup_mode?: string;
  }) {
    return http.post("/setup/paths", data);
  },

  async downloadModels(
    includeMultimodal = true,
    chatId?: string,
    opts?: { multimodalOnly?: boolean },
  ) {
    // Model packs are multi-GB; do not use the default axios timeout.
    return axios
      .post(
        `${API_BASE_URL}/setup/download-models`,
        {
          include_multimodal: includeMultimodal,
          chat_id: chatId || undefined,
          multimodal_only: Boolean(opts?.multimodalOnly),
        },
        { timeout: 0 },
      )
      .then((r) => r.data);
  },

  async selectChatModel(chatId: string) {
    return http.post("/setup/select-chat-model", { chat_id: chatId });
  },

  async startMultimodalServices(installDeps = false) {
    return http.post(
      `/setup/start-multimodal-services?install_deps=${installDeps ? "true" : "false"}`,
    );
  },

  async getMultimodalStatus() {
    return http.get("/setup/multimodal-status");
  },

  async startLocalLlm(chatId?: string) {
    // Metal load of 12B can take several minutes — no axios timeout.
    return axios
      .post(
        `${API_BASE_URL}/setup/start-local-llm`,
        { chat_id: chatId || undefined },
        { timeout: 0 },
      )
      .then((r) => r.data);
  },

  // ── Notes graph / vault ───────────────────────────────────────────────────

  async getNotesGraph(kb = "default"): Promise<import("@/lib/types").NotesGraphPayload> {
    return http.get(`/graph/notes${kbParam(kb)}`);
  },

  async getNoteNeighbors(
    noteId: string,
    kb = "default",
  ): Promise<import("@/lib/types").NotesGraphPayload> {
    return http.get(`/graph/notes/${encodeURIComponent(noteId)}/neighbors${kbParam(kb)}`);
  },

  async getNoteEntitySubgraph(
    text: string,
    kb = "default",
  ): Promise<import("@/lib/types").NotesGraphPayload> {
    return http.post(`/graph/entities/note-subgraph${kbParam(kb)}`, { text });
  },

  async rebuildNotesGraph(kb = "default") {
    return http.post(`/graph/notes/rebuild${kbParam(kb)}`);
  },

  async reingestVault(kb = "default") {
    return http.post(`/notes/reingest-vault${kbParam(kb)}`);
  },

  async exportChat(conversationId: string, format: "markdown" | "json" = "markdown") {
    if (format === "json") {
      return http.get(`/chat/conversations/${conversationId}/export`, { format });
    }
    const response = await axios.get(
      `${API_BASE_URL}/chat/conversations/${conversationId}/export`,
      { params: { format }, responseType: "text" },
    );
    return response.data as string;
  },

  // ── Finance ───────────────────────────────────────────────────────────────

  async getFinanceWorkspace(kb = "default") {
    return http.get(`/finance/workspace${kbParam(kb)}`) as Promise<import("@/lib/types").FinanceWorkspace>;
  },

  async createFinanceWorkspace(currency: string, kb = "default") {
    return http.post(`/finance/workspace${kbParam(kb)}`, { currency });
  },

  async resetFinanceAdministration(kb = "default"): Promise<{
    status: string;
    kb_id: string;
    message: string;
  }> {
    return http.post(`/finance/reset-administration${kbParam(kb)}`, {});
  },

  async listFinanceAccounts(kb = "default"): Promise<import("@/lib/types").FinanceAccount[]> {
    return http.get(`/finance/accounts${kbParam(kb)}`);
  },

  async createFinanceAccount(
    data: {
      name: string;
      account_type: string;
      opening_balance?: number;
      currency?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/accounts${kbParam(kb)}`, data);
  },

  async listFinanceTransactions(
    kb = "default",
    accountId?: string,
  ): Promise<import("@/lib/types").FinanceTransaction[]> {
    const params: Record<string, unknown> = {};
    if (accountId) params.account_id = accountId;
    return http.get(`/finance/transactions${kbParam(kb)}`, params);
  },

  async getFinanceSummary(
    kb = "default",
    days = 30,
  ): Promise<import("@/lib/types").FinanceSummary> {
    return http.get(`/finance/summary${kbParam(kb)}`, { days });
  },

  async getFinanceReport(
    kb = "default",
    start?: string,
    end?: string,
  ): Promise<import("@/lib/types").FinanceReport> {
    const params: Record<string, unknown> = {};
    if (start) params.start = start;
    if (end) params.end = end;
    return http.get(`/finance/report${kbParam(kb)}`, params);
  },

  async listFinanceBudgets(
    kb = "default",
    days = 30,
  ): Promise<import("@/lib/types").FinanceBudget[]> {
    return http.get(`/finance/budgets${kbParam(kb)}`, { days });
  },

  async createFinanceBudget(
    data: { name: string; amount?: number; currency?: string },
    kb = "default",
  ) {
    return http.post(`/finance/budgets${kbParam(kb)}`, data);
  },

  async listFinanceCategories(kb = "default"): Promise<import("@/lib/types").FinanceCategory[]> {
    return http.get(`/finance/categories${kbParam(kb)}`);
  },

  async createFinanceCategory(data: { name: string; notes?: string }, kb = "default") {
    return http.post(`/finance/categories${kbParam(kb)}`, data);
  },

  async deleteFinanceCategory(id: string, kb = "default") {
    return http.del(`/finance/categories/${id}${kbParam(kb)}`);
  },

  async listFinanceBills(kb = "default"): Promise<import("@/lib/types").FinanceBill[]> {
    return http.get(`/finance/bills${kbParam(kb)}`);
  },

  async createFinanceBill(
    data: {
      name: string;
      amount: number;
      repeat_freq?: string;
      date?: string;
      currency?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/bills${kbParam(kb)}`, data);
  },

  async deleteFinanceBill(id: string, kb = "default") {
    return http.del(`/finance/bills/${id}${kbParam(kb)}`);
  },

  async listFinancePiggyBanks(kb = "default"): Promise<import("@/lib/types").FinancePiggyBank[]> {
    return http.get(`/finance/piggy-banks${kbParam(kb)}`);
  },

  async createFinancePiggyBank(
    data: {
      name: string;
      account_id: string;
      target_amount: number;
      current_amount?: number;
      start_date?: string;
      target_date?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/piggy-banks${kbParam(kb)}`, data);
  },

  async deleteFinancePiggyBank(id: string, kb = "default") {
    return http.del(`/finance/piggy-banks/${id}${kbParam(kb)}`);
  },

  async listFinanceTags(kb = "default"): Promise<import("@/lib/types").FinanceTag[]> {
    return http.get(`/finance/tags${kbParam(kb)}`);
  },

  async createFinanceTag(data: { tag: string; description?: string }, kb = "default") {
    return http.post(`/finance/tags${kbParam(kb)}`, data);
  },

  async deleteFinanceTag(id: string, kb = "default") {
    return http.del(`/finance/tags/${id}${kbParam(kb)}`);
  },

  async listFinanceRecurrences(kb = "default"): Promise<import("@/lib/types").FinanceRecurrence[]> {
    return http.get(`/finance/recurrences${kbParam(kb)}`);
  },

  async createFinanceRecurrence(
    data: {
      title: string;
      amount: number;
      type?: string;
      source_id: string;
      destination_id: string;
      description?: string;
      first_date?: string;
      repeat_freq?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/recurrences${kbParam(kb)}`, data);
  },

  async deleteFinanceRecurrence(id: string, kb = "default") {
    return http.del(`/finance/recurrences/${id}${kbParam(kb)}`);
  },

  async listFinanceRuleGroups(kb = "default"): Promise<import("@/lib/types").FinanceRuleGroup[]> {
    return http.get(`/finance/rule-groups${kbParam(kb)}`);
  },

  async createFinanceRuleGroup(data: { title: string; description?: string }, kb = "default") {
    return http.post(`/finance/rule-groups${kbParam(kb)}`, data);
  },

  async deleteFinanceRuleGroup(id: string, kb = "default") {
    return http.del(`/finance/rule-groups/${id}${kbParam(kb)}`);
  },

  async listFinanceRules(kb = "default"): Promise<import("@/lib/types").FinanceRule[]> {
    return http.get(`/finance/rules${kbParam(kb)}`);
  },

  async createFinanceRule(
    data: {
      title: string;
      rule_group_id: string;
      trigger_type?: string;
      trigger_value: string;
      action_type?: string;
      action_value: string;
      trigger?: string;
      description?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/rules${kbParam(kb)}`, data);
  },

  async deleteFinanceRule(id: string, kb = "default") {
    return http.del(`/finance/rules/${id}${kbParam(kb)}`);
  },

  async listFinanceWebhooks(kb = "default"): Promise<import("@/lib/types").FinanceWebhook[]> {
    return http.get(`/finance/webhooks${kbParam(kb)}`);
  },

  async createFinanceWebhook(
    data: {
      title: string;
      url: string;
      trigger?: string;
      response?: string;
      delivery?: string;
      active?: boolean;
    },
    kb = "default",
  ) {
    return http.post(`/finance/webhooks${kbParam(kb)}`, data);
  },

  async deleteFinanceWebhook(id: string, kb = "default") {
    return http.del(`/finance/webhooks/${id}${kbParam(kb)}`);
  },

  async listFinanceObjectGroups(kb = "default"): Promise<import("@/lib/types").FinanceObjectGroup[]> {
    return http.get(`/finance/object-groups${kbParam(kb)}`);
  },

  async createFinanceObjectGroup(data: { title: string }, kb = "default") {
    return http.post(`/finance/object-groups${kbParam(kb)}`, data);
  },

  async updateFinanceObjectGroup(id: string, data: { title: string }, kb = "default") {
    return http.put(`/finance/object-groups/${id}${kbParam(kb)}`, data);
  },

  async deleteFinanceObjectGroup(id: string, kb = "default") {
    return http.del(`/finance/object-groups/${id}${kbParam(kb)}`);
  },

  async listFinanceExchangeRates(kb = "default"): Promise<import("@/lib/types").FinanceExchangeRate[]> {
    return http.get(`/finance/exchange-rates${kbParam(kb)}`);
  },

  async createFinanceExchangeRate(
    data: { date: string; from: string; to: string; rate: number },
    kb = "default",
  ) {
    return http.post(`/finance/exchange-rates${kbParam(kb)}`, data);
  },

  async deleteFinanceExchangeRate(id: string, kb = "default") {
    return http.del(`/finance/exchange-rates/${id}${kbParam(kb)}`);
  },

  async listFinanceAttachments(kb = "default"): Promise<import("@/lib/types").FinanceAttachment[]> {
    return http.get(`/finance/attachments${kbParam(kb)}`);
  },

  async createFinanceAttachment(
    data: {
      filename: string;
      attachable_type: string;
      attachable_id: string;
      title?: string;
      notes?: string;
      file?: File | null;
    },
    kb = "default",
  ) {
    const form = new FormData();
    form.append("filename", data.filename);
    form.append("attachable_type", data.attachable_type);
    form.append("attachable_id", data.attachable_id);
    if (data.title) form.append("title", data.title);
    if (data.notes) form.append("notes", data.notes);
    if (data.file) form.append("file", data.file);
    const response = await axios.post(
      `${API_BASE_URL}/finance/attachments${kbParam(kb)}`,
      form,
    );
    return response.data;
  },

  async downloadFinanceAttachment(id: string, kb = "default") {
    const response = await axios.get(
      `${API_BASE_URL}/finance/attachments/${id}/download${kbParam(kb)}`,
      { responseType: "blob" },
    );
    return response.data as Blob;
  },

  async deleteFinanceAttachment(id: string, kb = "default") {
    return http.del(`/finance/attachments/${id}${kbParam(kb)}`);
  },

  async searchFinance(
    query: string,
    kind: "transactions" | "accounts" = "transactions",
    kb = "default",
  ): Promise<import("@/lib/types").FinanceSearchResult> {
    return http.get(`/finance/search${kbParam(kb)}`, { query, kind });
  },

  async openFinanceWorkspace(kb = "default"): Promise<{ url: string }> {
    return http.post(`/finance/open${kbParam(kb)}`, {});
  },

  async createFinanceTransaction(
    data: {
      date?: string;
      description: string;
      amount: number;
      account_id: string;
      type?: string;
      transfer_account_id?: string;
      counterparty_name?: string;
      category?: string;
      budget_id?: string;
      currency?: string;
    },
    kb = "default",
  ) {
    return http.post(`/finance/transactions${kbParam(kb)}`, data);
  },

  async deleteFinanceTransaction(id: string, kb = "default") {
    return http.del(`/finance/transactions/${id}${kbParam(kb)}`);
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

  // ── Maintenance ───────────────────────────────────────────────────────────

  async getMaintenanceStatus(kb = "default"): Promise<{
    community_detection: {
      running: boolean;
      pending_nodes?: number;
      needed?: boolean;
      timer_armed?: boolean;
      idle_seconds?: number;
    };
    temporal_digests: { running: boolean };
    ingestion?: {
      active: number;
      last_completed_at?: string | null;
    };
    healthy?: boolean;
  }> {
    return http.get(`/admin/maintenance-status${kbParam(kb)}`);
  },

  async rebuildCommunities(kb = "default"): Promise<{ status: string; message: string }> {
    return http.post(`/admin/rebuild-communities${kbParam(kb)}`, {});
  },

  async buildTemporalDigests(period?: string, kb = "default"): Promise<{ status: string; message: string }> {
    return http.post(`/admin/build-temporal-digests${kbParam(kb)}`, { period: period ?? null });
  },

  async resetIngestionData(kb = "default"): Promise<{ status: string; message: string }> {
    return http.post(`/admin/reset-ingestion-data${kbParam(kb)}`, {});
  },

  async reingestAll(kb = "default"): Promise<{ status: string; notes_queued: number; message: string }> {
    return http.post(`/admin/reingest-all${kbParam(kb)}`, {});
  },
};
