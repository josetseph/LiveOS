/** Rewrite vault-file paths in note markdown after a move/rename. */
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
  return content.replaceAll(oldUrl, newUrl).replaceAll(from, to);
}
