"use client";

import type { RankedRow } from "@/lib/consumer-report";

export default function RankedBars({ rows }: { rows: RankedRow[] }) {
  const max = Math.max(...rows.map((row) => row.value.value || 0), 1);
  return (
    <div className="cr-bars" role="img" aria-label={rows.map((row) => `${row.label} ${row.value.display}`).join("，")}>
      {rows.map((row) => (
        <div className="cr-bar-row" key={`${row.label}-${row.value.display}`}>
          <span className="cr-bar-label">{row.label}{row.latin ? <em style={{ display: "block", fontSize: 11, color: "var(--cr-sub)" }}>{row.latin}</em> : null}</span>
          <div className="cr-bar-track"><div className={`cr-bar-fill ${row.tone || "good"}`} style={{ width: `${Math.max(1, (row.value.value || 0) / max * 100)}%` }} /></div>
          <span className="cr-bar-value">{row.value.display}</span>
        </div>
      ))}
    </div>
  );
}
