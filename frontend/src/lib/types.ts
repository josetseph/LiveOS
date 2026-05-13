export interface Note {
    id: string;
    title: string;
    content: string;
    created_at: string;
    updated_at?: string;
    processed?: boolean;
    failed?: boolean;
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
};
