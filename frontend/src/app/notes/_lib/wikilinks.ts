import type { Note } from "@/lib/types";

function normalizeLink(value: string | null | undefined): string {
  let text = (value || "").replace(/\\/g, "/").trim().toLowerCase();
  text = text.replace(/^\/+|\/+$/g, "");
  while (text.startsWith("./")) text = text.slice(2);
  return text.endsWith(".md") ? text.slice(0, -3) : text;
}

function folderOf(relPath: string): string {
  const cut = relPath.lastIndexOf("/");
  return cut === -1 ? "" : relPath.slice(0, cut);
}

/**
 * Closeness of two vault folders as `[steps, -sharedDepth]`, lower is nearer.
 *
 * Steps are tree hops (same folder 0, parent/child 1, sibling 2); shared depth
 * breaks ties so a sibling folder beats an unrelated one the same distance away.
 */
function folderProximity(sourceDir: string, targetDir: string): [number, number] {
  const a = sourceDir ? sourceDir.split("/") : [];
  const b = targetDir ? targetDir.split("/") : [];
  let shared = 0;
  while (shared < a.length && shared < b.length && a[shared] === b[shared]) shared += 1;
  return [a.length - shared + (b.length - shared), -shared];
}

type Candidate = { note: Note; relPath: string };

function pickClosest(candidates: Candidate[], sourceDir: string): Note | undefined {
  if (candidates.length === 0) return undefined;
  if (candidates.length === 1) return candidates[0].note;
  // Nearest folder wins; shallower and then alphabetical keep it deterministic.
  return [...candidates].sort((left, right) => {
    const [stepsA, sharedA] = folderProximity(sourceDir, folderOf(left.relPath));
    const [stepsB, sharedB] = folderProximity(sourceDir, folderOf(right.relPath));
    if (stepsA !== stepsB) return stepsA - stepsB;
    if (sharedA !== sharedB) return sharedA - sharedB;
    const byDepth =
      left.relPath.split("/").length - right.relPath.split("/").length;
    if (byDepth !== 0) return byDepth;
    return left.relPath.localeCompare(right.relPath);
  })[0].note;
}

/**
 * Indexed resolver for `[[targets]]`. Build once per notes list, then resolve
 * many times (click / hover) without re-scanning the vault.
 */
export class WikilinkResolver {
  private readonly byPath = new Map<string, Note>();
  private readonly byName = new Map<string, Candidate[]>();
  private readonly candidates: Candidate[] = [];

  constructor(notes: Note[]) {
    for (const note of notes) {
      const relPath = normalizeLink(note.rel_path);
      const candidate: Candidate = { note, relPath };
      this.candidates.push(candidate);
      if (relPath && !this.byPath.has(relPath)) this.byPath.set(relPath, note);
      const names = new Set([
        relPath ? relPath.split("/").pop() || "" : "",
        normalizeLink(note.title),
      ]);
      for (const name of names) {
        if (!name) continue;
        const bucket = this.byName.get(name);
        if (bucket) bucket.push(candidate);
        else this.byName.set(name, [candidate]);
      }
    }
  }

  resolve(target: string, sourceNote?: Note | null): Note | undefined {
    const key = normalizeLink(target);
    if (!key) return undefined;
    const sourceDir = folderOf(normalizeLink(sourceNote?.rel_path));

    // An explicit path is an exact request; a bare name is not, so it must not
    // match a root-level note ahead of a same-named note beside the source.
    if (key.includes("/")) {
      const exact = this.byPath.get(key);
      if (exact) return exact;
      const suffix = `/${key}`;
      const partial = this.candidates.filter((c) => c.relPath.endsWith(suffix));
      const best = pickClosest(partial, sourceDir);
      if (best) return best;
    }

    if (sourceDir) {
      const nested = this.byPath.get(`${sourceDir}/${key}`);
      if (nested) return nested;
    }

    const base = key.split("/").pop() || key;
    return pickClosest(this.byName.get(base) || [], sourceDir);
  }
}

/** One-shot convenience for call sites that don't hold a resolver yet. */
export function resolveNoteByWikilink(
  notes: Note[],
  target: string,
  sourceNote?: Note | null,
): Note | undefined {
  return new WikilinkResolver(notes).resolve(target, sourceNote);
}
