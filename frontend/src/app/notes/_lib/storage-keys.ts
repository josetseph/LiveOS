export function lastNoteStorageKey(kb: string) {
  return `orb:last-note-id:${kb || "default"}`;
}
