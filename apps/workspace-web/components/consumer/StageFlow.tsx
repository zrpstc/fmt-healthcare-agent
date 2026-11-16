"use client";

import type { Stage, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function StageFlow({ stages, footnote, glossary }: { stages: Stage[]; footnote: string; glossary: GlossaryEntry[] }) {
  return (
    <div>
      <div className="cr-stage-flow">
        {stages.map((stage) => {
          const shown = stage.members.slice(0, 3);
          const more = stage.members.length - shown.length;
          return (
            <article className="cr-stage" key={stage.title}>
              <h4>{stage.title}</h4>
              <div className="cr-stage-members">
                {shown.join("、")}{more > 0 ? `等${more}种` : ""}
              </div>
              <span className="cr-stage-backup">{stage.backup_label}</span>
              <p><RichText text={stage.meaning} glossary={glossary} /></p>
            </article>
          );
        })}
      </div>
      <p className="cr-stage-footnote">{footnote}</p>
    </div>
  );
}
