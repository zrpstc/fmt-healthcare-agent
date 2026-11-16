"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { parseRichText } from "@/lib/consumer-pure.mjs";
import type { GlossaryEntry } from "@/lib/consumer-report";

interface GlossaryProps {
  glossary: GlossaryEntry[];
}

function useGlossaryMap(glossary: GlossaryEntry[]) {
  return useMemo(() => new Map(glossary.map((entry) => [entry.term_id, entry])), [glossary]);
}

export function GlossaryTerm({
  termId,
  label,
  glossary,
}: {
  termId: string;
  label: string;
  glossary: GlossaryEntry[];
}) {
  const map = useGlossaryMap(glossary);
  const entry = map.get(termId);
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!entry) {
    return <span>{label}</span>;
  }

  const onOpen = () => {
    setOpen(true);
    if (buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      if (window.innerWidth >= 1024) {
        setPosition({
          left: Math.min(window.innerWidth - 340, Math.max(12, rect.left)),
          top: Math.min(window.innerHeight - 220, rect.bottom + 8),
        });
      } else {
        setPosition(null);
      }
    }
  };

  return (
    <>
      <button ref={buttonRef} type="button" className="cr-term" onClick={onOpen} aria-label={`解释：${entry.name}`}>
        {label}
      </button>
      {open && (
        <div
          className={position ? "cr-term-popover" : "cr-term-drawer"}
          style={position ? { left: position.left, top: position.top } : undefined}
          role="dialog"
          aria-label={entry.name}
        >
          {!position && (
            <button type="button" className="cr-drawer-close" onClick={() => { setOpen(false); buttonRef.current?.focus(); }} aria-label="关闭">
              <X size={18} />
            </button>
          )}
          <div className="cr-popover-title">{entry.name}</div>
          <p>{entry.text}</p>
        </div>
      )}
    </>
  );
}

export function RichText({ text, glossary }: { text: string; glossary: GlossaryEntry[] }) {
  const tokens = parseRichText(text);
  return (
    <>
      {tokens.map((token, index) => {
        if (token.kind === "term") {
          return <GlossaryTerm key={`${token.termId}-${index}`} termId={token.termId} label={token.text} glossary={glossary} />;
        }
        if (token.kind === "italic") {
          return <em key={`i-${index}`}>{token.text}</em>;
        }
        return <span key={`t-${index}`}>{token.text}</span>;
      })}
    </>
  );
}

export function TermBanner({ termIds, glossary }: { termIds: string[]; glossary: GlossaryEntry[] }) {
  if (!termIds.length) return null;
  const map = new Map(glossary.map((entry) => [entry.term_id, entry]));
  const entries = termIds.map((id) => map.get(id)).filter((entry): entry is GlossaryEntry => Boolean(entry));
  if (!entries.length) return null;
  return (
    <div className="cr-banner">
      <span aria-hidden="true">i</span>
      <div>
        {entries.map((entry) => (
          <div key={entry.term_id}>
            <strong>{entry.name}</strong>：{entry.text}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Callout({ tone, text, glossary }: { tone: "good" | "neutral" | "watch" | "consult"; text: string; glossary: GlossaryEntry[] }) {
  return <div className={`cr-callout ${tone}`} role="note"><RichText text={text} glossary={glossary} /></div>;
}

export function EvidenceBadge({ value }: { value?: string }) {
  if (!value) return null;
  return <span className="cr-badge evidence">{value}</span>;
}

export function ReliabilityBadge({ value }: { value?: string }) {
  if (!value) return null;
  return <span className="cr-badge reliability">检出可靠度：{value}</span>;
}
