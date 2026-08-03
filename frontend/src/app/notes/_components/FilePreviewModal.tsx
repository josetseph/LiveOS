"use client";

import { FolderOpen, X } from "lucide-react";
import { motion } from "framer-motion";
import { BlobMediaPlayer } from "@/components/blob-media-player";
import {
  isDesktopApp,
  revealInFolderLabel,
} from "@/lib/desktop";
import type { FilePreview } from "@/lib/types";

type FilePreviewModalProps = {
  filePreview: FilePreview;
  currentKB: string;
  onClose: () => void;
  onReveal: () => void;
};

export function FilePreviewModal({
  filePreview,
  currentKB,
  onClose,
  onReveal,
}: FilePreviewModalProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="relative max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-white/10 bg-black/95 shadow-2xl backdrop-blur-xl"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <h2 className="text-lg font-bold text-white">
            {filePreview.filename}
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void onReveal()}
              className="flex h-8 items-center gap-1.5 rounded-lg bg-white/5 px-2.5 text-white/60 transition-all hover:bg-white/10 hover:text-white sm:px-3"
              title={isDesktopApp() ? revealInFolderLabel() : "Open file"}
              aria-label={isDesktopApp() ? revealInFolderLabel() : "Open file"}
            >
              <FolderOpen className="h-4 w-4" />
              <span className="hidden text-xs sm:inline">
                {isDesktopApp() ? revealInFolderLabel() : "Open"}
              </span>
            </button>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
              title="Close file preview"
              aria-label="Close file preview"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
        <div className="max-h-[calc(90vh-80px)] overflow-y-auto p-6">
          {filePreview.type === "image" && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={filePreview.url}
              alt={filePreview.filename}
              className="mx-auto max-w-full rounded-lg"
            />
          )}
          {filePreview.type === "pdf" && (
            <iframe
              src={filePreview.url}
              className="h-[70vh] w-full rounded-lg"
              title="PDF preview"
            />
          )}
          {filePreview.type === "video" && (
            <div className="flex min-h-[240px] items-center justify-center">
              <BlobMediaPlayer
                url={filePreview.url}
                kbId={currentKB}
                kind="video"
                className="mx-auto max-h-[70vh] w-full max-w-full rounded-lg bg-black"
              />
            </div>
          )}
          {filePreview.type === "audio" && (
            <div className="flex items-center justify-center">
              <BlobMediaPlayer
                url={filePreview.url}
                kbId={currentKB}
                kind="audio"
                className="w-full max-w-2xl"
              />
            </div>
          )}
          {filePreview.type === "other" && (
            <div className="text-center">
              <p className="mb-4 text-white/60">
                Preview not available for this file type
              </p>
              <button
                type="button"
                onClick={() => void onReveal()}
                className="inline-flex items-center gap-2 rounded-xl bg-linear-to-br from-purple-500 to-pink-500 px-6 py-3 text-white transition-all hover:scale-105"
              >
                <FolderOpen className="h-5 w-5" />
                {isDesktopApp() ? revealInFolderLabel() : "Open file"}
              </button>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
