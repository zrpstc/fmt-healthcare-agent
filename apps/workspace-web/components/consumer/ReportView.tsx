"use client";

import type { Block, ConsumerReport, GlossaryEntry, Section } from "@/lib/consumer-report";
import { RichText, Callout, TermBanner } from "./RichText";
import StatusCard from "./StatusCard";
import FindingCard from "./FindingCard";
import SummaryHero from "./SummaryHero";
import ReportHeader from "./ReportHeader";
import SectionNav from "./SectionNav";
import StackedBar from "./StackedBar";
import RankedBars from "./RankedBars";
import DonutChart from "./DonutChart";
import OverallAssessment from "./OverallAssessment";
import HealthScore from "./HealthScore";
import TierScale from "./TierScale";
import TaxonCard from "./TaxonCard";
import CategoryCard from "./CategoryCard";
import StageFlow from "./StageFlow";
import ReportTable from "./ReportTable";
import CardGrid from "./CardGrid";
import ScatterPlot from "./ScatterPlot";
import KnowledgeGraphBlock from "./KnowledgeGraphBlock";
import RiskDistribution from "./RiskDistribution";
import ActionCard from "./ActionCard";
import RetestTimeline from "./RetestTimeline";
import LearnMore from "./LearnMore";

function BlockView({ block, glossary }: { block: Block; glossary: GlossaryEntry[] }) {
  switch (block.type) {
    case "paragraph":
      return <p className="cr-paragraph"><RichText text={block.text} glossary={glossary} /></p>;
    case "callout":
      return <Callout tone={block.tone} text={block.text} glossary={glossary} />;
    case "stacked_bar":
      return <StackedBar segments={block.segments} glossary={glossary} />;
    case "donut":
      return <DonutChart block={block} glossary={glossary} />;
    case "ranked_bars":
      return <RankedBars rows={block.rows} block={block} />;
    case "tier_scales":
      return (
        <div>
          {block.rows.map((row) => (
            <TierScale key={row.label} label={row.label} value={row.value} tier={row.tier} note={row.note ?? undefined} glossary={glossary} />
          ))}
        </div>
      );
    case "taxon_cards":
      return (
        <div className="cr-taxon-grid">
          {block.cards.map((card) => <TaxonCard key={`${card.name}-${card.value.display}`} card={card} glossary={glossary} />)}
        </div>
      );
    case "category_cards":
      return (
        <div className="cr-category-grid">
          {block.cards.map((card) => <CategoryCard key={card.title} card={card} glossary={glossary} />)}
        </div>
      );
    case "stage_flow":
      return <StageFlow stages={block.stages} footnote={block.footnote} glossary={glossary} />;
    case "table":
      return <ReportTable block={block} glossary={glossary} />;
    case "card_grid":
      return <CardGrid cards={block.cards} glossary={glossary} />;
    case "scatter":
      return <ScatterPlot block={block} />;
    case "risk_distribution":
      return <RiskDistribution block={block} glossary={glossary} />;
    default:
      return null;
  }
}

function SectionView({ section, report }: { section: Section; report: ConsumerReport }) {
  return (
    <section className="cr-section" id={section.id}>
      <div className="cr-section-head">
        <h2>{section.title}</h2>
        {section.intro && <p><RichText text={section.intro} glossary={report.glossary} /></p>}
      </div>
      <TermBanner termIds={section.terms_banner} glossary={report.glossary} />
      {section.subsections.map((subsection) => (
        <div className="cr-subsection" id={subsection.id} key={subsection.id}>
          <h3>{subsection.title}</h3>
          {subsection.blocks.map((block, index) => (
            <div className="cr-block" key={`${subsection.id}-${index}`}>
              <BlockView block={block} glossary={report.glossary} />
            </div>
          ))}
          {subsection.summary && (
            <p className="cr-subsection-summary"><RichText text={subsection.summary} glossary={report.glossary} /></p>
          )}
          {subsection.graph && (
            <KnowledgeGraphBlock graph={subsection.graph} references={report.references} glossary={report.glossary} />
          )}
        </div>
      ))}
    </section>
  );
}

export default function ReportView({ data, mode }: { data: ConsumerReport; mode: "internal" | "public" }) {
  const contentSections = data.sections.filter((section) => section.id !== "learn");
  const learn = data.sections.find((section) => section.id === "learn");
  const navSections: Section[] = [
    ...data.sections.filter((section) => section.id !== "learn"),
    { id: "actions", nav_label: "行动建议", title: "接下来可以做什么", source_chapters: [], terms_banner: [], subsections: [] },
    ...(learn ? [learn] : []),
  ];
  return (
    <div className="cr-root">
      <div className="cr-shell">
        <SectionNav sections={navSections} />
        <main className="cr-main">
          <div className="cr-page">
            <ReportHeader sample={data.sample} mode={mode} />
            <SummaryHero report={data} />
            <HealthScore score={data.summary.health_score} />
            <OverallAssessment items={data.summary.assessments ?? []} glossary={data.glossary} />
            <div className="cr-status-grid">
              {data.summary.status_cards.map((card) => (
                <StatusCard key={card.id} card={card} glossary={data.glossary} />
              ))}
            </div>
            <div className="cr-findings">
              {data.summary.key_findings.map((finding) => (
                <FindingCard key={finding.rank} finding={finding} glossary={data.glossary} />
              ))}
            </div>

            {contentSections.map((section) => <SectionView key={section.id} section={section} report={data} />)}

            <section className="cr-section" id="actions">
              <div className="cr-section-head">
                <h2>接下来可以做什么</h2>
                <p>这些建议来自本报告中的发现，不包含药品、益生菌或补充剂推荐。</p>
              </div>
              <div className="cr-actions">
                {data.actions.map((action) => <ActionCard key={action.finding_code} action={action} glossary={data.glossary} />)}
              </div>
              <RetestTimeline retest={data.retest} />
              <div className="cr-red-flags">
                <h3>出现这些情况请就医</h3>
                <ul>{data.red_flags.map((flag) => <li key={flag}>{flag}</li>)}</ul>
              </div>
            </section>

            {learn && (
              <section className="cr-section" id="learn">
                <div className="cr-section-head">
                  <h2>{learn.title}</h2>
                  <p>{learn.intro}</p>
                </div>
                <LearnMore report={data} />
              </section>
            )}

            <p style={{ marginTop: 34, fontSize: 12, color: "var(--cr-sub)" }}>
              本报告用于健康管理参考，不用于疾病诊断，也不替代医生的判断。
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
