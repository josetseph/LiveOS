"use client";

import { X } from "lucide-react";
import { motion } from "framer-motion";

type DatePickerModalProps = {
  createdAt: string;
  pendingDateChange: string | null;
  onPendingChange: (isoDate: string) => void;
  onClose: () => void;
};

export function DatePickerModal({
  createdAt,
  pendingDateChange,
  onPendingChange,
  onClose,
}: DatePickerModalProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="relative mx-4 w-full max-w-md rounded-2xl border border-white/10 bg-black/95 p-6 shadow-2xl backdrop-blur-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold text-white">Set Note Date</h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-white/60 transition-all hover:bg-white/10 hover:text-white"
            title="Close date picker"
            aria-label="Close date picker"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <input
          type="datetime-local"
          defaultValue={new Date(createdAt).toISOString().slice(0, 16)}
          onChange={(e) => {
            if (e.target.value) {
              const isoDate = new Date(e.target.value).toISOString();
              console.log("Date changed to:", isoDate);
              onPendingChange(isoDate);
            }
          }}
          className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-white backdrop-blur-xl focus:border-purple-500/50 focus:outline-none"
          autoFocus
          title="Select note date"
          aria-label="Select note date"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/80 transition-all hover:bg-white/10"
          >
            {pendingDateChange ? "Save & Close" : "Close"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
