"use client";

import { useEffect, useRef } from "react";

export function CustomCursor() {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const isPointerRef = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const x = e.clientX;
      const y = e.clientY;

      const target = e.target as HTMLElement;
      isPointerRef.current =
        window.getComputedStyle(target).cursor === "pointer" ||
        target.tagName === "BUTTON" ||
        target.tagName === "A";

      const scale = isPointerRef.current ? 1.5 : 1;
      const innerScale = isPointerRef.current ? 0.5 : 1;

      if (outerRef.current) {
        outerRef.current.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) scale(${scale})`;
      }
      if (innerRef.current) {
        innerRef.current.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) scale(${innerScale})`;
      }
    };

    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  return (
    <>
      <div
        ref={outerRef}
        className="pointer-events-none fixed left-0 top-0 z-9999 mix-blend-difference will-change-transform hidden md:block"
        style={{ contain: "layout style paint" }}
      >
        <div className="h-4 w-4 rounded-full border-2 border-white" />
      </div>
      <div
        ref={innerRef}
        className="pointer-events-none fixed left-0 top-0 z-9999 mix-blend-difference will-change-transform hidden md:block"
        style={{ contain: "layout style paint" }}
      >
        <div className="h-2 w-2 rounded-full bg-white" />
      </div>
    </>
  );
}
