"use client";

import type { TaxonCard as TaxonCardType, GlossaryEntry } from "@/lib/consumer-report";
import { RichText, EvidenceBadge, ReliabilityBadge } from "./RichText";

export default function TaxonCard({ card, glossary }: { card: TaxonCardType; glossary: GlossaryEntry[] }) {
  return (
    <article className="cr-taxon-card">
      <h4 className="cr-taxon-name">
        {card.name}
        {card.first_mention && card.latin ? <em className="cr-taxon-latin">（{card.latin}）</em> : null}
      </h4>
      <div className="cr-taxon-value">{card.value.display}</div>
      {card.text && <p><RichText text={card.text} glossary={glossary} /></p>}
      <div className="cr-badge-row">
        <EvidenceBadge value={card.evidence_badge} />
        <ReliabilityBadge value={card.reliability_badge} />
      </div>
    </article>
  );
}
