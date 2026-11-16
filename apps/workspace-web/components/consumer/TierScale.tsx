"use client";

import { tierPosition } from "@/lib/consumer-pure.mjs";
import type { Tier, Num, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";
export default function TierScale({
  label,
  value,
  tier,
  note,
  glossary,
}: {
  label: string;
  value: Num;
  tier: Tier;
  note?: string;
  glossary: GlossaryEntry[];
}) {
  const position = tierPosition(tier) ?? 50;
  const tone = tier.tone === "watch" ? "#9A5410" : tier.tone === "good" ? "#2E7150" : "#45606A";
  return (
    <div className="cr-tier-scale">
      <div className="cr-tier-head">
        <span><strong><RichText text={label} glossary={glossary} /></strong> {value.display}</span>
        <span className={`cr-tag ${tier.tone}`}>{tier.label}</span>
      </div>
      <svg
        className="cr-tier-svg"
        viewBox="0 0 100 22"
        role="img"
        aria-label={`${label} ${value.display}，${tier.label}，${tier.phrase}`}
      >
        <rect x="0" y="6" width="100" height="10" rx="5" fill="#ECE8E0" />
        <rect x="5" y="6" width="90" height="10" rx="4" fill="#D3E4DF" />
        <line x1={position} y1="2" x2={position} y2="20" stroke={tone} strokeWidth="2.4" />
        <circle cx={position} cy="11" r="3.6" fill={tone} />
      </svg>
      <div className="cr-tier-note">{tier.phrase}</div>
      {note && <div className="cr-tier-note"><RichText text={note} glossary={glossary} /></div>}
    </div>
  );
}
