"use client";

import type { RankedBarsBlock, RankedRow } from "@/lib/consumer-report";

export default function RankedBars({ rows, block }: { rows: RankedRow[]; block?: RankedBarsBlock }) {
  const axis = block?.axis;
  const ticks = axis?.ticks ?? [];
  const tickMax = ticks.length ? Math.max(...ticks.map((tick) => tick.value || 0)) : 0;
  const max = Math.max(tickMax, ...rows.map((row) => row.value.value || 0), 1);
  const label = (block?.title ? `${block.title}：` : "") + rows.map((row) => `${row.label} ${row.value.display}`).join("，");
  return (
    <figure className="cr-chart cr-bars">
      {block?.title && <figcaption className="cr-chart-title">{block.title}</figcaption>}
      {axis && (
        <div className="cr-bar-row cr-bar-axis-head" aria-hidden="true">
          <span>{axis.category_label}</span>
          <span />
          <span />
        </div>
      )}
      <div role="img" aria-label={label}>
        {rows.map((row) => (
          <div className="cr-bar-row" key={`${row.label}-${row.value.display}`}>
            <span className="cr-bar-label">{row.label}{row.latin ? <em style={{ display: "block", fontSize: 11, color: "var(--cr-sub)" }}>{row.latin}</em> : null}</span>
            <div className="cr-bar-track"><div className={`cr-bar-fill ${row.tone || "good"}`} style={{ width: `${Math.max(1, (row.value.value || 0) / max * 100)}%` }} /></div>
            <span className="cr-bar-value">{row.value.display}</span>
          </div>
        ))}
      </div>
      {ticks.length > 1 && (
        <div className="cr-bar-row cr-bar-ticks" aria-hidden="true">
          <span />
          <div className="cr-bar-tick-track">
            {ticks.map((tick) => (
              <span key={tick.display} style={{ left: `${((tick.value || 0) / max) * 100}%` }}>{tick.display}</span>
            ))}
          </div>
          <span />
        </div>
      )}
      {axis && (
        <div className="cr-bar-row cr-bar-axis-title" aria-hidden="true">
          <span />
          <span>{axis.value_label}</span>
          <span />
        </div>
      )}
      {block?.caption &&<p className="cr-chart-caption">{block.caption}</p>}
    </figure>
  );
}
