import {
  Decoration,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
  EditorView,
  WidgetType,
} from "@codemirror/view";

const WIKILINK_RE = /\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]/g;

class WikilinkWidget extends WidgetType {
  constructor(
    readonly target: string,
    readonly label: string,
  ) {
    super();
  }

  eq(other: WikilinkWidget) {
    return this.target === other.target && this.label === other.label;
  }

  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-wikilink";
    span.textContent = this.label;
    span.setAttribute("data-wikilink-target", this.target);
    span.setAttribute("data-wikilink-alias", this.label === this.target ? "" : this.label);
    span.title = this.target;
    return span;
  }

  ignoreEvent() {
    return false;
  }
}

/**
 * Highlight Obsidian-style [[wikilinks]].
 * On inactive lines: hide brackets and show only the display text (colored + underlined).
 * On the active (editing) line: show full [[syntax]] with mark styling.
 */
export function createWikilinkDecorations() {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;

      constructor(view: EditorView) {
        this.decorations = this.build(view);
      }

      update(update: ViewUpdate) {
        if (
          update.docChanged ||
          update.viewportChanged ||
          update.selectionSet
        ) {
          this.decorations = this.build(update.view);
        }
      }

      build(view: EditorView): DecorationSet {
        const marks: ReturnType<Decoration["range"]>[] = [];
        const doc = view.state.doc.toString();
        const activeLine = view.state.doc.lineAt(
          view.state.selection.main.head,
        ).number;
        WIKILINK_RE.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = WIKILINK_RE.exec(doc)) !== null) {
          const from = m.index;
          const to = m.index + m[0].length;
          const target = m[1].trim();
          const alias = m[2]?.trim() || "";
          const label = alias || target;
          const line = view.state.doc.lineAt(from).number;

          if (line === activeLine) {
            marks.push(
              Decoration.mark({
                class: "cm-wikilink",
                attributes: {
                  "data-wikilink-target": target,
                  "data-wikilink-alias": alias,
                  title: label,
                },
              }).range(from, to),
            );
          } else {
            marks.push(
              Decoration.replace({
                widget: new WikilinkWidget(target, label),
              }).range(from, to),
            );
          }
        }
        return Decoration.set(marks, true);
      }
    },
    { decorations: (v) => v.decorations },
  );
}

export function wikilinkClickHandler(
  onWikilinkClick?: (target: string, alias?: string) => void,
) {
  return EditorView.domEventHandlers({
    click(event, view) {
      if (!onWikilinkClick) return false;
      const target = event.target as HTMLElement | null;
      const el = target?.closest?.("[data-wikilink-target]") as HTMLElement | null;
      if (!el || !view.dom.contains(el)) return false;
      const linkTarget = el.getAttribute("data-wikilink-target");
      const alias = el.getAttribute("data-wikilink-alias") || undefined;
      if (linkTarget) {
        event.preventDefault();
        onWikilinkClick(linkTarget, alias || undefined);
        return true;
      }
      return false;
    },
  });
}

export function wikilinkHoverHandler(
  onWikilinkHover?: (
    target: string,
    rect: DOMRect,
    alias?: string,
  ) => void,
  onWikilinkLeave?: () => void,
) {
  return EditorView.domEventHandlers({
    mouseover(event, view) {
      if (!onWikilinkHover) return false;
      const target = event.target as HTMLElement | null;
      const el = target?.closest?.("[data-wikilink-target]") as HTMLElement | null;
      if (!el || !view.dom.contains(el)) return false;
      const linkTarget = el.getAttribute("data-wikilink-target");
      const alias = el.getAttribute("data-wikilink-alias") || undefined;
      if (linkTarget) {
        onWikilinkHover(linkTarget, el.getBoundingClientRect(), alias || undefined);
      }
      return false;
    },
    mouseout(event, view) {
      if (!onWikilinkLeave) return false;
      const related = event.relatedTarget as HTMLElement | null;
      const leaving =
        related &&
        view.dom.contains(related) &&
        related.closest?.("[data-wikilink-target]");
      if (!leaving) {
        onWikilinkLeave();
      }
      return false;
    },
  });
}
