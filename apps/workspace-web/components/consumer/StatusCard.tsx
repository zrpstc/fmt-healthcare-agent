"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { StatusCard as StatusCardType } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function StatusCard({ card, glossary }: { card: StatusCardType; glossary: import("@/lib/consumer-report").GlossaryEntry[] }) {
  return (
    <Link className="cr-status-card" href={card.anchor}>
      <span className="cr-kicker">{card.label}</span>
      <strong>{card.tier_label}</strong>
      <span className={`cr-tag ${card.tone}`}>{card.tone === "good" ? "良好" : card.tone === "watch" ? "需留意" : card.tone === "consult" ? "请就医" : "供了解"}</span>
      <p><RichText text={card.line} glossary={glossary} /></p>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 8, fontSize: 12, color: "var(--cr-brand)" }}>
        查看对应部分 <ChevronRight size={14} />
      </span>
    </Link>
  );
}
