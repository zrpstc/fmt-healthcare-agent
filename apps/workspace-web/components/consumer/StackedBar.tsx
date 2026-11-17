"use client";

import type { StackedSegment, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

const PALETTE = ["#145C58", "#4A7C74", "#8AB8A6", "#C6B694", "#7F929B", "#D8CFC2", "#B8C8C0"];

export default function StackedBar({ segments, glossary }: { segments: StackedSegment[]; glossary: GlossaryEntry[] }) {
  const total = segments.reduce((sum, item) => sum + (item.value.value || 0), 0) || 1;
  return (
    <div className="cr-stacked">
      <div className="cr-stacked-bar" role="img" aria-label={segments.map((item) => `${item.label} ${item.value.display}`).join("，")}>
        {segments.map((item, index) => {
          const width = Math.max(0, (item.value.value || 0) / total * 100);
          if (width < 0.2) return null;
          return (
            <span
              key={item.label}
              style={{ width: `${width}%`, background: item.color_key === "unclassified" ? "#D8CFC2" : PALETTE[index % PALETTE.length] }}
              title={`${item.label} ${item.value.display}`}
            />
          );
        })}
      </div>
      <div className="cr-legend">
        {segments.map((item, index) => (
          <div className="cr-legend-item" key={item.label}>
            <i style={{ background: item.color_key === "unclassified" ? "#D8CFC2" : PALETTE[index % PALETTE.length] }} />
            <div>
              <strong>{item.label} {item.value.display}</strong>
              {item.note && <div><RichText text={item.note} glossary={glossary} /></div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
