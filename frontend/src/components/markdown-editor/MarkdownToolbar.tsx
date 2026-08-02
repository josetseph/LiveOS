"use client";

import type { ComponentType, ChangeEvent, ReactNode } from "react";
import type { EditorView } from "@codemirror/view";
import {
  Bold,
  Italic,
  Strikethrough,
  Code,
  Link,
  FileCode,
  Quote,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  ListTodo,
  Minus,
  Paperclip,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  runMarkdownAction,
  type MarkdownAction,
} from "./markdownCommands";

interface ToolItem {
  action: MarkdownAction;
  icon: ComponentType<{ className?: string }>;
  label: string;
  shortcut?: string;
}

const formattingTools: ToolItem[] = [
  { action: "bold", icon: Bold, label: "Bold", shortcut: "⌘B" },
  { action: "italic", icon: Italic, label: "Italic", shortcut: "⌘I" },
  {
    action: "strikethrough",
    icon: Strikethrough,
    label: "Strikethrough",
    shortcut: "⌘⇧S",
  },
  { action: "inlineCode", icon: Code, label: "Inline code", shortcut: "⌘E" },
];

const insertTools: ToolItem[] = [
  { action: "link", icon: Link, label: "Link", shortcut: "⌘K" },
  { action: "codeBlock", icon: FileCode, label: "Code block", shortcut: "⌘⇧C" },
  { action: "quote", icon: Quote, label: "Quote", shortcut: "⌘⇧." },
];

const structureTools: ToolItem[] = [
  { action: "h1", icon: Heading1, label: "Heading 1", shortcut: "⌘1" },
  { action: "h2", icon: Heading2, label: "Heading 2", shortcut: "⌘2" },
  { action: "h3", icon: Heading3, label: "Heading 3", shortcut: "⌘3" },
  { action: "bulletList", icon: List, label: "Bullet list", shortcut: "⌘⇧8" },
  {
    action: "numberedList",
    icon: ListOrdered,
    label: "Numbered list",
    shortcut: "⌘⇧7",
  },
  { action: "taskList", icon: ListTodo, label: "Task list", shortcut: "⌘⇧9" },
  {
    action: "horizontalRule",
    icon: Minus,
    label: "Horizontal rule",
    shortcut: "⌘⇧R",
  },
];

function ToolButton({
  tool,
  onAction,
}: {
  tool: ToolItem;
  onAction: (action: MarkdownAction) => void;
}) {
  const Icon = tool.icon;
  return (
    <button
      type="button"
      onMouseDown={(e) => {
        e.preventDefault();
        onAction(tool.action);
      }}
      title={
        tool.shortcut ? `${tool.label} (${tool.shortcut})` : tool.label
      }
      aria-label={tool.label}
      className={cn(
        "group relative flex h-7 w-7 items-center justify-center rounded-md",
        "text-white/50 transition-colors hover:bg-white/10 hover:text-white/90",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  );
}

function ToolGroup({
  tools,
  onAction,
}: {
  tools: ToolItem[];
  onAction: (action: MarkdownAction) => void;
}) {
  return (
    <div className="flex items-center gap-px rounded-md bg-white/[0.03] p-0.5">
      {tools.map((tool) => (
        <ToolButton key={tool.action} tool={tool} onAction={onAction} />
      ))}
    </div>
  );
}

export interface MarkdownToolbarProps {
  view: EditorView | null;
  className?: string;
  /** Extra controls (e.g. Attach) rendered after structure tools. */
  trailing?: ReactNode;
  onAttachFile?: (e: ChangeEvent<HTMLInputElement>) => void;
  attachDisabled?: boolean;
}

export function MarkdownToolbar({
  view,
  className,
  trailing,
  onAttachFile,
  attachDisabled,
}: MarkdownToolbarProps) {
  const onAction = (action: MarkdownAction) => {
    runMarkdownAction(view, action);
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 border-b border-white/10",
        "bg-white/[0.02] px-3 py-2",
        className,
      )}
    >
      <ToolGroup tools={formattingTools} onAction={onAction} />
      <div className="mx-0.5 h-5 w-px bg-white/10" />
      <ToolGroup tools={insertTools} onAction={onAction} />
      <div className="mx-0.5 h-5 w-px bg-white/10" />
      <ToolGroup tools={structureTools} onAction={onAction} />
      {onAttachFile && (
        <>
          <div className="mx-0.5 h-5 w-px bg-white/10" />
          <div className="flex items-center gap-px rounded-md bg-white/[0.03] p-0.5">
            <input
              type="file"
              id="md-toolbar-file-upload"
              className="hidden"
              onChange={onAttachFile}
              disabled={attachDisabled}
            />
            <label
              htmlFor="md-toolbar-file-upload"
              title="Attach file"
              aria-label="Attach file"
              className={cn(
                "flex h-7 w-7 cursor-pointer items-center justify-center rounded-md",
                "text-white/50 transition-colors hover:bg-white/10 hover:text-white/90",
                attachDisabled && "pointer-events-none opacity-40",
              )}
            >
              <Paperclip className="h-3.5 w-3.5" />
            </label>
          </div>
        </>
      )}
      {trailing}
    </div>
  );
}
