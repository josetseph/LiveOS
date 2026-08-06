import type { NoteAttachment } from "./types";

const ATTACHMENT_REGEX =
  /(?:!\[([^\]]*)\]\(([^)]+)\)|\[([📎🖇🎤][^\]]+)\]\(([^)]+)\))/g;

export function parseNoteAttachments(content: string): NoteAttachment[] {
  const attachments: NoteAttachment[] = [];
  let m: RegExpExecArray | null;
  const regex = new RegExp(ATTACHMENT_REGEX.source, ATTACHMENT_REGEX.flags);
  while ((m = regex.exec(content)) !== null) {
    const label = (m[1] ?? m[3] ?? "file").replace(/^[📎🖇🎤]\s*/, "");
    const url = m[2] ?? m[4] ?? "";
    if (!url) continue;
    attachments.push({ label, url, raw: m[0] });
  }
  return attachments;
}
