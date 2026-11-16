"use client";

import type { TableBlock, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function ReportTable({ block, glossary }: { block: TableBlock; glossary: GlossaryEntry[] }) {
  return (
    <div>
      <div className="cr-table-wrap">
        <table className="cr-table">
          <thead>
            <tr>{block.columns.map((column) => <th key={column}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}><RichText text={String(cell)} glossary={glossary} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.footnote && <p className="cr-table-footnote">{block.footnote}</p>}
    </div>
  );
}
