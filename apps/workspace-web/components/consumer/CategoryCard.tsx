"use client";

import type { CategoryCard as CategoryCardType, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";
import TaxonCard from "./TaxonCard";

export default function CategoryCard({ card, glossary }: { card: CategoryCardType; glossary: GlossaryEntry[] }) {
  return (
    <article className="cr-category-card">
      <h4>{card.title}</h4>
      <p className="cr-category-text"><RichText text={card.text} glossary={glossary} /></p>
      {card.total && (
        <div className="cr-category-total">
          <span>合计占比</span>
          <strong>{card.total.display}</strong>
        </div>
      )}
      {card.tier && (
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--cr-sub)" }}>
          {card.tier.label} · {card.tier.phrase}
        </div>
      )}
      {card.members.length > 0 ? (
        <div className="cr-members">
          {card.members.map((member) => (
            <TaxonCard key={`${member.name}-${member.value.display}`} card={member} glossary={glossary} />
          ))}
        </div>
      ) : card.absent_text ? (
        <p style={{ margin: "10px 0 0", fontSize: 13, color: "var(--cr-sub)" }}>{card.absent_text}</p>
      ) : null}
      {card.callout && (
        <div className={`cr-callout ${card.callout.tone}`} style={{ marginTop: 10 }}>
          <RichText text={card.callout.text} glossary={glossary} />
        </div>
      )}
    </article>
  );
}
