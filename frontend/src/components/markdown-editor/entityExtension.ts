import {
  Decoration,
  EditorView,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
  keymap,
} from "@codemirror/view";
import {
  autocompletion,
  completionKeymap,
  type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete";
import { Prec } from "@codemirror/state";
import { api } from "@/lib/api";

export interface EntitySuggestion {
  node_id: string;
  name: string;
  node_type: string;
}

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Find word-boundary ranges for known entity names in document text. */
export function findEntityRanges(
  content: string,
  entities: EntitySuggestion[],
): { from: number; to: number; entity: EntitySuggestion }[] {
  const ranges: { from: number; to: number; entity: EntitySuggestion }[] = [];
  for (const entity of entities) {
    if (!entity.name) continue;
    const re = new RegExp(`\\b${escapeRegex(entity.name)}\\b`, "gi");
    let m: RegExpExecArray | null;
    while ((m = re.exec(content)) !== null) {
      ranges.push({
        from: m.index,
        to: m.index + entity.name.length,
        entity,
      });
    }
  }
  ranges.sort((a, b) => a.from - b.from);
  const out: typeof ranges = [];
  let last = 0;
  for (const r of ranges) {
    if (r.from < last) continue;
    out.push(r);
    last = r.to;
  }
  return out;
}

/**
 * Decorations for scanned entity mentions. Rebuild when the entity list changes
 * by reconfiguring the extension via a Compartment (caller handles that).
 */
export function createEntityDecorations(entities: EntitySuggestion[]) {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;

      constructor(view: EditorView) {
        this.decorations = this.build(view);
      }

      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = this.build(update.view);
        }
      }

      build(view: EditorView): DecorationSet {
        const marks: ReturnType<Decoration["range"]>[] = [];
        const doc = view.state.doc.toString();
        for (const r of findEntityRanges(doc, entities)) {
          marks.push(
            Decoration.mark({
              class: "cm-entity-mention",
              attributes: {
                "data-node-id": r.entity.node_id,
                "data-name": r.entity.name,
              },
            }).range(r.from, r.to),
          );
        }
        return Decoration.set(marks, true);
      }
    },
    {
      decorations: (v) => v.decorations,
    },
  );
}

/**
 * Click handler: if the user clicks an entity decoration, fire onEntityClick.
 */
export function entityClickHandler(
  onEntityClick?: (nodeId: string, name: string) => void,
) {
  return EditorView.domEventHandlers({
    click(event, view) {
      if (!onEntityClick) return false;
      const target = event.target as HTMLElement | null;
      const el = target?.closest?.("[data-node-id]") as HTMLElement | null;
      if (!el || !view.dom.contains(el)) return false;
      const nodeId = el.getAttribute("data-node-id");
      const name = el.getAttribute("data-name");
      if (nodeId && name) {
        onEntityClick(nodeId, name);
        return true;
      }
      return false;
    },
  });
}

function getWordBefore(
  text: string,
  pos: number,
  minLength = 3,
): { word: string; from: number; to: number } | null {
  let start = pos;
  while (start > 0 && /\S/.test(text[start - 1])) start--;
  const word = text.slice(start, pos);
  if (word.length < minLength) return null;
  return { word, from: start, to: pos };
}

/**
 * CM6 autocomplete source that searches graph entities as the user types.
 */
export function entityCompletionSource(kb: string) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastReq = 0;

  return async (
    context: CompletionContext,
  ): Promise<CompletionResult | null> => {
    const wordInfo = getWordBefore(
      context.state.doc.toString(),
      context.pos,
    );
    if (!wordInfo) return null;
    if (!context.explicit && wordInfo.word.length < 3) return null;

    const reqId = ++lastReq;
    const results = await new Promise<EntitySuggestion[]>((resolve) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const found = await api.searchEntities(wordInfo.word, kb, 6);
          resolve(found);
        } catch {
          resolve([]);
        }
      }, 250);
    });

    if (reqId !== lastReq) return null;
    if (!results.length) return null;

    return {
      from: wordInfo.from,
      options: results.map((e) => ({
        label: e.name,
        detail: e.node_type || "entity",
        type: "text",
        apply: e.name,
      })),
      filter: false,
    };
  };
}

export function entityAutocomplete(kb: string) {
  return [
    autocompletion({
      override: [entityCompletionSource(kb)],
      closeOnBlur: true,
      activateOnTyping: true,
      maxRenderedOptions: 8,
    }),
    Prec.highest(keymap.of(completionKeymap)),
  ];
}
