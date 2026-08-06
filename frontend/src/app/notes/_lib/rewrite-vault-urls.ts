function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Rewrite vault-file paths in note markdown after a move/rename.
 *
 * Single pass with longest-match-first alternation. The previous chained
 * `replaceAll(oldUrl, newUrl).replaceAll(from, to)` re-matched inside
 * just-rewritten URLs (moving `foo.png` into `attachments/` produced
 * `attachments/attachments/foo.png`) and the corruption was then persisted
 * by autosave.
 */
export function rewriteVaultPathsInContent(
  content: string,
  currentKB: string,
  from: string,
  to: string,
): string {
  const oldUrl = `/vault-files/${currentKB}/${from}`;
  const newUrl = `/vault-files/${currentKB}/${to}`;
  if (!content.includes(from) && !content.includes(oldUrl)) {
    return content;
  }
  const pattern = new RegExp(
    `${escapeRegExp(oldUrl)}|${escapeRegExp(from)}`,
    "g",
  );
  return content.replace(pattern, (match, offset: number) => {
    if (match === oldUrl) return newUrl;
    // Bare relative path: only rewrite inside a markdown link/embed target
    // (preceded by "(", "<" or "[["), never incidental prose mentions.
    const prev = offset > 0 ? content[offset - 1] : "";
    if (prev === "(" || prev === "<" || prev === "[") return to;
    return match;
  });
}
