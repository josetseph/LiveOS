export interface Note {
    id: string;
    title: string;
    content: string;
    created_at: string;
    updated_at?: string;
    processed?: boolean;
    failed?: boolean;
    processing_stage?: string | null;
    processing_model?: string | null;
}

export interface FilePreview {
    url: string;
    filename: string;
    type: "image" | "pdf" | "audio" | "other";
}

/** Subset used by the chat page when previewing a linked note. */
export interface NotePreview {
    id: string;
    title: string;
    content: string;
}

/** Status shape returned by GET /api/v1/notes/:id/status */
export type NoteStatus = {
    id: string;
    processed: boolean;
    failed: boolean;
    status: string;
    processing_stage?: string | null;
    processing_model?: string | null;
};

export type ChatStatus = {
    request_id: string;
    conversation_id?: string;
    stage: string;
    model?: string | null;
    done?: boolean;
    result?: {
        answer?: string;
        thinking?: string | null;
        conversation_id?: string;
        assistant_message_id?: string;
    };
    error?: string;
};

export interface ChatConversation {
    id: string;
    kb_id: string;
    title: string;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface ChatMessageRecord {
    id: string;
    conversation_id: string;
    role: "user" | "assistant";
    content: string;
    thinking?: string | null;
    created_at?: string | null;
}

/** Knowledge base metadata returned by GET /api/v1/kb */
export interface KnowledgeBase {
    id: string;
    name: string;
    slug?: string;
    kuzu_path?: string;
    qdrant_col_cores?: string;
    typesense_collection?: string;
    created_at: string | null;
}
