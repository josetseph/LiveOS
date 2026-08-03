import type { Note } from "@/lib/types";

export function resolveNoteByWikilink(
  notes: Note[],
  target: string,
): Note | undefined {
  const key = target.toLowerCase().trim().replace(/\\/g, "/");
  const base = key.split("/").pop()?.replace(/\.md$/i, "") || key;
  return notes.find((n) => {
    const title = (n.title || "").toLowerCase();
    const rel = (n.rel_path || "").replace(/\\/g, "/").toLowerCase();
    const stem = rel.split("/").pop()?.replace(/\.md$/i, "") || "";
    const withoutExt = rel.endsWith(".md") ? rel.slice(0, -3) : rel;
    return (
      title === key ||
      stem === key ||
      withoutExt === key ||
      title === base ||
      stem === base
    );
  });
}
