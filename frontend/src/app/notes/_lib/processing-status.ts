import type { Note } from "@/lib/types";

export function getProcessingLabel(
  note: Pick<Note, "processing_stage" | "processing_model">,
) {
  const stage = note.processing_stage || "Processing";
  return note.processing_model ? `${stage} (${note.processing_model})` : stage;
}

export function isPendingReingestNote(note: Note) {
  const stage = note.processing_stage || "";
  return (
    !note.processed &&
    !note.failed &&
    (stage.includes("pending re-ingest") ||
      stage.includes("pending ingest") ||
      stage.includes("re-ingest when ready") ||
      stage.includes("Changed on disk"))
  );
}

/** True only while a user-triggered ingest pipeline is running. */
export function isActiveProcessingNote(note: Note) {
  if (note.processed || note.failed) return false;
  if (isPendingReingestNote(note)) return false;
  const stage = (note.processing_stage || "").trim();
  if (!stage || stage === "Saved") return false;
  // Explicit ingest queue / pipeline stages only (never watcher / autosave markers).
  const activePrefixes = [
    "Queued for ingestion",
    "Queued for vault re-ingest",
    "Starting ingestion",
  ];
  if (activePrefixes.some((p) => stage.startsWith(p))) return true;
  // Ingestion tracker writes intermediate labels like "Extracting entities…" —
  // treat anything else non-terminal as active only if it does not look like a
  // watcher/save status.
  const nonPipeline = [
    "External",
    "Changed on disk",
    "pending",
    "Saved",
    "Ingestion complete",
    "Ingestion failed",
  ];
  if (nonPipeline.some((p) => stage.includes(p) || stage.startsWith(p))) {
    return false;
  }
  return true;
}
