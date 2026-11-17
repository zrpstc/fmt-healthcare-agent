"use client";

import type { DonutBlock, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

const PALETTE = ["#145C58", "#4A7C74", "#8AB8A6", "#C6B694", "#7F929B", "#B8C8C0", "#9C8466"];
const UNCLASSIFIED = "#D8CFC2";
const R = 42;
const C = 2 * Math.PI * R;

function colorFor(colorKey: string, index: number) {
  return colorKey === "unclassified" ? UNCLASSIFIED : PALETTE[index % PALETTE.length];
}

export default function DonutChart({ block, glossary }: { block: DonutBlock; glossary: GlossaryEntry[] }) {
  const total = block.segments.reduce((sum, item) => sum + (item.value.value || 0), 0) || 1;
  let offset = 0;
  const arcs = block.segments.map((item, index) => {
    const length = Math.max(0, (item.value.value || 0) / total) * C;
    const arc = { item, index, length, offset };
    offset += length;
    return arc;
  });
  return (
    <figure className="cr-chart cr-donut">
      <figcaption className="cr-chart-title">{block.title}</figcaption>
      <div className="cr-donut-body">
        <svg
          className="cr-donut-svg"
          viewBox="0 0 100 100"
          role="img"
          aria-label={`${block.title}：` + block.segments.map((item) => `${item.label} ${item.value.display}`).join("，")}
        >
          <circle cx="50" cy="50" r={R} fill="none" stroke="var(--cr-track)" strokeWidth="14" />
          {arcs.map(({ item, index, length, offset: start }) => (
            length > 0.05 ? (
              <circle
                key={item.label}
                cx="50"
                cy="50"
                r={R}
                fill="none"
                stroke={colorFor(item.color_key, index)}
                strokeWidth="14"
                strokeDasharray={`${length} ${C - length}`}
                strokeDashoffset={-start}
                transform="rotate(-90 50 50)"
              >
                <title>{`${item.label} ${item.value.display}`}</title>
              </circle>
            ) : null
          ))}
          {block.center_value && <text x="50" y="50" textAnchor="middle" className="cr-donut-value">{block.center_value}</text>}
          {block.center_label && <text x="50" y="61" textAnchor="middle" className="cr-donut-label">{block.center_label}</text>}
        </svg>
        <div className="cr-donut-legend">
          {block.segments.map((item, index) => (
            <div className="cr-legend-item" key={item.label}>
              <i style={{ background: colorFor(item.color_key, index) }} />
              <div>
                <strong>{item.label} {item.value.display}</strong>
                {item.note && <div><RichText text={item.note} glossary={glossary} /></div>}
              </div>
            </div>
          ))}
        </div>
      </div>
      {block.caption && <p className="cr-chart-caption">{block.caption}</p>}
    </figure>
  );
}
