"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import {
  EditorView,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
} from "@codemirror/view";
import { EditorState, Compartment, Prec } from "@codemirror/state";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import { searchKeymap } from "@codemirror/search";
import { api } from "@/lib/api";
import { liveMarkdownExtensions } from "./markdownHighlight";
import { createLivePreviewHideMarks } from "./livePreviewHideMarks";
import {
  insertAtCursor as insertAtCursorCmd,
  runMarkdownAction,
} from "./markdownCommands";
import {
  createEntityDecorations,
  entityAutocomplete,
  entityClickHandler,
  type EntitySuggestion,
} from "./entityExtension";
import { createWikilinkDecorations, wikilinkClickHandler, wikilinkHoverHandler } from "./wikilinkExtension";
import { createMediaEmbedDecorations } from "./mediaEmbedExtension";
import { MarkdownToolbar } from "./MarkdownToolbar";

export interface MarkdownNoteEditorProps {
  value: string;
  onChange: (value: string) => void;
  onEntityClick?: (nodeId: string, name: string) => void;
  onWikilinkClick?: (target: string, alias?: string) => void;
  onWikilinkHover?: (target: string, rect: DOMRect, alias?: string) => void;
  onWikilinkLeave?: () => void;
  onAttachFile?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  attachDisabled?: boolean;
  kb?: string;
  placeholder?: string;
  className?: string;
  /** Show formatting toolbar above the editor (default true). */
  showToolbar?: boolean;
}

export interface MarkdownNoteEditorHandle {
  insertAtCursor: (text: string) => void;
  focus: () => void;
  /** Compatibility shim — CM6 has no textarea; returns null. */
  textarea: HTMLTextAreaElement | null;
  getView: () => EditorView | null;
}

function formattingKeymap() {
  return keymap.of([
    {
      key: "Mod-b",
      run: (view) => {
        runMarkdownAction(view, "bold");
        return true;
      },
    },
    {
      key: "Mod-i",
      run: (view) => {
        runMarkdownAction(view, "italic");
        return true;
      },
    },
    {
      key: "Mod-Shift-s",
      run: (view) => {
        runMarkdownAction(view, "strikethrough");
        return true;
      },
    },
    {
      key: "Mod-e",
      run: (view) => {
        runMarkdownAction(view, "inlineCode");
        return true;
      },
    },
    {
      key: "Mod-k",
      run: (view) => {
        runMarkdownAction(view, "link");
        return true;
      },
    },
    {
      key: "Mod-Shift-c",
      run: (view) => {
        runMarkdownAction(view, "codeBlock");
        return true;
      },
    },
    {
      key: "Mod-1",
      run: (view) => {
        runMarkdownAction(view, "h1");
        return true;
      },
    },
    {
      key: "Mod-2",
      run: (view) => {
        runMarkdownAction(view, "h2");
        return true;
      },
    },
    {
      key: "Mod-3",
      run: (view) => {
        runMarkdownAction(view, "h3");
        return true;
      },
    },
    {
      key: "Mod-Shift-8",
      run: (view) => {
        runMarkdownAction(view, "bulletList");
        return true;
      },
    },
    {
      key: "Mod-Shift-7",
      run: (view) => {
        runMarkdownAction(view, "numberedList");
        return true;
      },
    },
    {
      key: "Mod-Shift-9",
      run: (view) => {
        runMarkdownAction(view, "taskList");
        return true;
      },
    },
    {
      key: "Mod-Shift-r",
      run: (view) => {
        runMarkdownAction(view, "horizontalRule");
        return true;
      },
    },
    {
      key: "Mod-Shift-.",
      run: (view) => {
        runMarkdownAction(view, "quote");
        return true;
      },
    },
  ]);
}

const MarkdownNoteEditor = forwardRef<
  MarkdownNoteEditorHandle,
  MarkdownNoteEditorProps
>(function MarkdownNoteEditor(
  {
    value,
    onChange,
    onEntityClick,
    onWikilinkClick,
    onWikilinkHover,
    onWikilinkLeave,
    onAttachFile,
    attachDisabled,
    kb = "default",
    placeholder = "Start writing...",
    className,
    showToolbar = true,
  },
  ref,
) {
  const cmRef = useRef<ReactCodeMirrorRef>(null);
  const entityDecorationsCompartment = useRef(new Compartment()).current;
  const [view, setView] = useState<EditorView | null>(null);
  const [scannedEntities, setScannedEntities] = useState<EntitySuggestion[]>(
    [],
  );

  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const v = cmRef.current?.view;
      if (!v) return;
      insertAtCursorCmd(v, text);
    },
    focus() {
      cmRef.current?.view?.focus();
    },
    get textarea() {
      return null;
    },
    getView() {
      return cmRef.current?.view ?? null;
    },
  }));

  // Scan note text for entity mentions once on mount (parent remounts per note)
  useEffect(() => {
    if (!value || value.length < 10) {
      setScannedEntities([]);
      return;
    }
    let cancelled = false;
    api
      .scanTextEntities(value, kb)
      .then((entities) => {
        if (!cancelled) setScannedEntities(entities);
      })
      .catch(() => {
        if (!cancelled) setScannedEntities([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kb]);

  // Rebuild entity decorations when the scanned list changes
  useEffect(() => {
    const v = cmRef.current?.view;
    if (!v) return;
    v.dispatch({
      effects: entityDecorationsCompartment.reconfigure(
        createEntityDecorations(scannedEntities),
      ),
    });
  }, [scannedEntities, entityDecorationsCompartment]);

  const extensions = useMemo(
    () => [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      drawSelection(),
      history(),
      EditorView.lineWrapping,
      EditorState.allowMultipleSelections.of(true),
      markdown({ base: markdownLanguage }),
      ...liveMarkdownExtensions,
      createLivePreviewHideMarks(),
      cmPlaceholder(placeholder),
      createWikilinkDecorations(),
      createMediaEmbedDecorations(kb),
      entityDecorationsCompartment.of(
        createEntityDecorations(scannedEntities),
      ),
      ...entityAutocomplete(kb),
      entityClickHandler(onEntityClick),
      wikilinkClickHandler(onWikilinkClick),
      wikilinkHoverHandler(onWikilinkHover, onWikilinkLeave),
      Prec.high(formattingKeymap()),
      keymap.of([
        ...defaultKeymap,
        ...historyKeymap,
        indentWithTab,
        ...searchKeymap,
      ]),
    ],
    // scannedEntities initial; updates via compartment.reconfigure
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      kb,
      placeholder,
      onEntityClick,
      onWikilinkClick,
      onWikilinkHover,
      onWikilinkLeave,
      entityDecorationsCompartment,
    ],
  );

  const handleCreateEditor = useCallback((v: EditorView) => {
    setView(v);
  }, []);

  const handleChange = useCallback(
    (doc: string) => {
      onChange(doc);
    },
    [onChange],
  );

  return (
    <div className={`flex h-full min-h-0 flex-col ${className ?? ""}`}>
      {showToolbar && (
        <MarkdownToolbar
          view={view}
          onAttachFile={onAttachFile}
          attachDisabled={attachDisabled}
        />
      )}
      <div className="min-h-0 flex-1 overflow-hidden px-4 py-3">
        <CodeMirror
          ref={cmRef}
          value={value}
          height="100%"
          theme="none"
          basicSetup={false}
          extensions={extensions}
          onChange={handleChange}
          onCreateEditor={handleCreateEditor}
          className="h-full [&_.cm-editor]:h-full"
        />
      </div>
    </div>
  );
});

export default MarkdownNoteEditor;
