"use client";

import React from "react";

/** A vertical bar that reports horizontal drag deltas, for resizing panes. */
const DragHandle: React.FC<{ onDrag: (delta: number) => void; className?: string }> = ({
  onDrag,
  className = "",
}) => {
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    let lastX = e.clientX;
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - lastX;
      if (delta !== 0) {
        lastX = ev.clientX;
        onDrag(delta);
      }
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      className={`z-20 w-1 flex-shrink-0 cursor-col-resize bg-neutral-800 transition-colors hover:bg-fra-yellow active:bg-fra-yellow ${className}`}
      onMouseDown={handleMouseDown}
    />
  );
};

export default DragHandle;
