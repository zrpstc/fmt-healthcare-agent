"use client";

import type { ConsumerReport } from "@/lib/consumer-report";
import { RichText } from "./RichText";

export default function SummaryHero({ report }: { report: ConsumerReport }) {
  return (
    <section className="cr-hero" aria-labelledby="cr-summary-headline">
      <h2 id="cr-summary-headline"><RichText text={report.summary.headline} glossary={report.glossary} /></h2>
      <p>这份报告用于健康管理参考，不用于疾病诊断。读完后可以先看“行动建议”。</p>
      <div className="cr-hero-actions">
        <a className="cr-button" href="#actions">看行动建议</a>
        <a className="cr-button secondary" href="#learn">了解方法与数据</a>
      </div>
    </section>
  );
}
