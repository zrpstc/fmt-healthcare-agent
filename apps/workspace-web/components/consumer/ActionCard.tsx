"use client";

import type { Action, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function ActionCard({ action, glossary }: { action: Action; glossary: GlossaryEntry[] }) {
  return (
    <article className="cr-action">
      <span className="cr-action-because">因为：{action.because}</span>
      <h3>{action.title}</h3>
      <p><RichText text={action.how} glossary={glossary} /></p>
      {action.examples && action.examples.length > 0 && (
        <div className="cr-examples">
          {action.examples.map((example) => <span className="cr-example" key={example}>{example}</span>)}
        </div>
      )}
    </article>
  );
}
