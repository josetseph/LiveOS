import {
  Decoration,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
  EditorView,
} from "@codemirror/view";
import { syntaxTree } from "@codemirror/language";

const HIDE_NODE_TYPES = new Set([
  "HeaderMark",
  "EmphasisMark",
  "StrikethroughMark",
  "CodeMark",
  "QuoteMark",
  // LinkMark intentionally omitted — hiding it glues label+URL together.
  // Images/attachments are handled by mediaEmbedExtension instead.
]);

/**
 * Obsidian-style live preview: hide markdown syntax markers on lines that
 * don't contain the cursor. The active line keeps raw markers for editing.
 */
export function createLivePreviewHideMarks() {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;

      constructor(view: EditorView) {
        this.decorations = this.build(view);
      }

      update(update: ViewUpdate) {
        if (
          update.docChanged ||
          update.selectionSet ||
          update.viewportChanged
        ) {
          this.decorations = this.build(update.view);
        }
      }

      build(view: EditorView): DecorationSet {
        const marks: ReturnType<Decoration["range"]>[] = [];
        const sel = view.state.selection.main;
        const activeLine = view.state.doc.lineAt(sel.head).number;

        for (const { from, to } of view.visibleRanges) {
          syntaxTree(view.state).iterate({
            from,
            to,
            enter: (node) => {
              if (!HIDE_NODE_TYPES.has(node.name)) return;
              // Don't hide if cursor overlaps this marker's line
              const line = view.state.doc.lineAt(node.from).number;
              if (line === activeLine) return;
              // Keep a tiny bit of URL visible? Full hide for LinkMark/URL when inactive
              if (node.to > node.from) {
                marks.push(
                  Decoration.replace({}).range(node.from, node.to),
                );
              }
            },
          });
        }
        return Decoration.set(marks, true);
      }
    },
    { decorations: (v) => v.decorations },
  );
}
