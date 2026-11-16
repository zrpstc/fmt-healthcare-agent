"use client";

import type { MetaboliteCard, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export function ProductCard({ card, glossary }: { card: MetaboliteCard; glossary: GlossaryEntry[] }) {
  return (
    <article className="cr-product-card">
      <h4>{card.title}</h4>
      <p><RichText text={card.text} glossary={glossary} /></p>
      <div className="cr-product-status">{card.status}</div>
      {card.tier && <div style={{ fontSize: 12, color: "var(--cr-sub)" }}>{card.tier.label}</div>}
      {card.members && card.members.length > 0 && (
        <div className="cr-product-members"><strong>主要参与的菌：</strong>{card.members.join("、")}</div>
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
