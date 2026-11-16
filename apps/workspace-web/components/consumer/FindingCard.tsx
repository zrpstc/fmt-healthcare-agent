"use client";

import Link from "next/link";
import type { FindingCard as FindingCardType, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function FindingCard({ finding, glossary }: { finding: FindingCardType; glossary: GlossaryEntry[] }) {
  return (
    <div className={`cr-finding ${finding.tone}`}>
      <span className="cr-rank">{finding.rank}</span>
      <div>
        <h3>{finding.title}</h3>
        <div className="cr-big">{finding.big.display}{finding.big.unit && !finding.big.display.includes(finding.big.unit) ? ` ${finding.big.unit}` : ""}</div>
        <p className="cr-compare">{finding.compare}</p>
        <p><RichText text={finding.meaning} glossary={glossary} /></p>
        <Link href={finding.anchor} style={{ display: "inline-block", marginTop: 8, fontSize: 12, fontWeight: 700 }}>
          查看相关部分 →
        </Link>
      </div>
    </div>
  );
}
