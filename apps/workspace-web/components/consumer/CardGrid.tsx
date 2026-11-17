"use client";

import { useId, useState } from "react";
import type { MetaboliteCard, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export function ProductCard({ card, glossary }: { card: MetaboliteCard; glossary: GlossaryEntry[] }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const expandable = Boolean(card.details && card.details.length);
  return (
    <article className={`cr-product-card${expandable ? " is-expandable" : ""}${open ? " is-open" : ""}`}>
      <div className="cr-product-head">
        <h4>{card.title}</h4>
        {card.score && (
          <div className={`cr-product-score ${card.tone}`} aria-label={`潜力评分 ${card.score.display}分，满分100分`}>
            <strong>{card.score.display}</strong><span>/100</span>
          </div>
        )}
      </div>
      <p><RichText text={card.text} glossary={glossary} /></p>
      <div className="cr-product-status">
        {card.status}
        {card.score_label && <span className={`cr-tag ${card.tone}`}>{card.score_label}</span>}
      </div>
      {card.score && (
        <div className="cr-product-meter" aria-hidden="true">
          <span className={card.tone} style={{ width: `${Math.max(0, Math.min(100, card.score.value || 0))}%` }} />
        </div>
      )}
      {card.tier && <div style={{ fontSize: 12, color: "var(--cr-sub)" }}>{card.tier.label}</div>}
      {card.members && card.members.length > 0 && (
        <div className="cr-product-members"><strong>主要参与的菌：</strong>{card.members.join("、")}</div>
      )}
      {expandable && (
        <>
          <button
            type="button"
            className="cr-product-toggle"
            aria-expanded={open}
            aria-controls={detailId}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "收起评分依据" : "展开评分依据"}
          </button>
          <dl className="cr-product-details" id={detailId}>
            {card.details!.map((row) => (
              <div key={row.label}>
                <dt>{row.label}</dt>
                <dd>{row.text}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </article>
  );
}

export function DrugClassCard({ card, glossary }: { card: MetaboliteCard; glossary: GlossaryEntry[] }) {
  return <ProductCard card={card} glossary={glossary} />;
}

export function SubstrateCard({ card, glossary }: { card: MetaboliteCard; glossary: GlossaryEntry[] }) {
  return <ProductCard card={card} glossary={glossary} />;
}

export default function CardGrid({ cards, glossary }: { cards: MetaboliteCard[]; glossary: GlossaryEntry[] }) {
  return (
    <div className="cr-grid-cards">
      {cards.map((card) => <ProductCard key={card.title} card={card} glossary={glossary} />)}
    </div>
  );
}

export function MetaboliteGrid({ cards, glossary }: { cards: MetaboliteCard[]; glossary: GlossaryEntry[] }) {
  return <CardGrid cards={cards} glossary={glossary} />;
}
