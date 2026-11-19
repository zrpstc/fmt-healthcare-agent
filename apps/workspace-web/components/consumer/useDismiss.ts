"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * Close a floating panel (term popover, bottom drawer) when the reader
 * clicks or taps anywhere outside it, presses Escape, or — for panels pinned
 * next to a word with `position: fixed` — scrolls or resizes the page, since
 * the panel would otherwise stay put while the word moves away.
 */
export function useDismiss(
  open: boolean,
  insideRefs: Array<RefObject<HTMLElement | null>>,
  onClose: (reason: "outside" | "escape" | "scroll") => void,
  { closeOnScroll = false }: { closeOnScroll?: boolean } = {},
) {
  const latest = useRef({ insideRefs, onClose });
  latest.current = { insideRefs, onClose };

  useEffect(() => {
    if (!open) return;
    const isInside = (target: EventTarget | null) =>
      target instanceof Node && latest.current.insideRefs.some((ref) => ref.current?.contains(target));
    const onPointerDown = (event: PointerEvent) => {
      if (!isInside(event.target)) latest.current.onClose("outside");
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") latest.current.onClose("escape");
    };
    const onScroll = (event: Event) => {
      // Scrolling inside the panel itself (long text) must not close it.
      if (!isInside(event.target)) latest.current.onClose("scroll");
    };
    const onResize = () => latest.current.onClose("scroll");
    document.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown);
    if (closeOnScroll) {
      window.addEventListener("scroll", onScroll, { capture: true, passive: true });
      window.addEventListener("resize", onResize);
    }
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open, closeOnScroll]);
}
