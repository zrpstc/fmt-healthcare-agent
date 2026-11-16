"use client";

import type { TableBlock, GlossaryEntry } from "@/lib/consumer-report";
import ReportTable from "./ReportTable";

export function ToxinTable({ block, glossary }: { block: TableBlock; glossary: GlossaryEntry[] }) {
  return <ReportTable block={block} glossary={glossary} />;
}

export function VitaminTable({ block, glossary }: { block: TableBlock; glossary: GlossaryEntry[] }) {
  return <ReportTable block={block} glossary={glossary} />;
}
