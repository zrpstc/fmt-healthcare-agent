"use client";

import type { Assessment, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function OverallAssessment({ items, glossary }: { items: Assessment[]; glossary: GlossaryEntry[] }) {
  if (!items.length) return null;
  return (
    <section className="cr-assessments" aria-labelledby="cr-assessment-title">
      <h3 id="cr-assessment-title">总体评价</h3>
      <div className="cr-assessment-grid">
        {items.map((item) => (
          <article className={`cr-assessment ${item.tone}`} key={item.id}>
            <div className="cr-assessment-head">
              <span className="cr-kicker">{item.title}</span>
              <span className={`cr-tag ${item.tone}`}>{item.verdict}</span>
            </div>
            <p className="cr-assessment-text"><RichText text={item.text} glossary={glossary} /></p>
            <ul>
              {item.points.map((point) => <li key={point}>{point}</li>)}
            </ul>
            <a className="cr-assessment-link" href={item.anchor}>查看详情</a>
          </article>
        ))}
      </div>
    </section>
  );
}
