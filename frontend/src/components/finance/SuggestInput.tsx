"use client";

import { useState } from "react";
import { FIELD_INPUT } from "./utils";

export function SuggestInput({
  value,
  onChange,
  suggestions,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const filtered = suggestions
    .filter((item) => item.toLowerCase().includes((value || "").toLowerCase()))
    .slice(0, 8);
  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // Delay so click on suggestion registers.
          window.setTimeout(() => setOpen(false), 120);
        }}
        className={FIELD_INPUT}
        placeholder={placeholder}
        autoComplete="off"
      />
      {open && filtered.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-lg border border-white/15 bg-[#12141c] py-1 shadow-lg">
          {filtered.map((item) => (
            <li key={item}>
              <button
                type="button"
                className="block w-full px-3 py-1.5 text-left text-sm text-white/85 hover:bg-teal-500/15"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(item);
                  setOpen(false);
                }}
              >
                {item}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
