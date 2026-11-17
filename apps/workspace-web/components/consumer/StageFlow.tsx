"use client";

import type { Stage, GlossaryEntry } from "@/lib/consumer-report";
import { RichText } from "./RichText";

const SHOWN = 6;

export default function StageFlow({ stages, footnote, glossary }: { stages: Stage[]; footnote: string; glossary: GlossaryEntry[] }) {
  return (
    <div>
      <div className="cr-stage-flow">
        {stages.map((stage) => {
          const details = stage.member_details && stage.member_details.length
            ? stage.member_details
            : stage.members.map((name) => ({ name, value: null, basis: "gene" as const }));
          const shown = details.slice(0, SHOWN);
          const more = details.length - shown.length;
          return (
            <article className="cr-stage" key={stage.title}>
              <h4>{stage.title}</h4>
              <ul className="cr-stage-members">
                {shown.map((member) => (
                  <li key={member.name} className={member.basis === "taxonomy" ? "is-taxonomy" : undefined}>
                    <span>{member.name}</span>
                    {member.value && <span className="cr-stage-value">{member.value.display}</span>}
                    {member.basis === "taxonomy" && <span className="cr-stage-basis">按菌种特性</span>}
                  </li>
                ))}
              </ul>
              {more > 0 && <div className="cr-stage-more">另有{more}种</div>}
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
