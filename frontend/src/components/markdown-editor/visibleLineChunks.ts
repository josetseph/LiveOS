import type { EditorView } from "@codemirror/view";

/**
 * The viewport's visible ranges, extended to whole-line boundaries and merged
 * where they touch. Decoration plugins scan these slices instead of
 * `doc.toString()` so large notes don't pay a full-document regex pass on
 * every keystroke/scroll. All our inline patterns (media embeds, wikilinks,
 * entity mentions) are single-line, so line-extension never cuts a match.
 */
export function visibleLineChunks(
  view: EditorView,
): { text: string; offset: number }[] {
  const merged: { from: number; to: number }[] = [];
  for (const r of view.visibleRanges) {
    const from = view.state.doc.lineAt(r.from).from;
    const to = view.state.doc.lineAt(r.to).to;
    const last = merged[merged.length - 1];
    if (last && from <= last.to) {
      last.to = Math.max(last.to, to);
    } else {
      merged.push({ from, to });
    }
  }
  return merged.map((c) => ({
    text: view.state.doc.sliceString(c.from, c.to),
    offset: c.from,
  }));
}
