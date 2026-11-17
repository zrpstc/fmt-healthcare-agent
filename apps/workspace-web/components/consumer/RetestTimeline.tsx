"use client";

import type { Retest } from "@/lib/consumer-report";

export default function RetestTimeline({ retest }: { retest: Retest | null }) {
  if (!retest) return null;
  const focus = retest.focus.join("、");
  return (
    <div className="cr-timeline">
      <div className="cr-timeline-step">
        <strong>现在</strong>
        <span>按行动建议调整饮食和记录习惯。</span>
      </div>
      <div className="cr-timeline-step">
        <strong>第 2 周</strong>
        <span>回看排便记录；症状没有改善时提前咨询。</span>
      </div>
      <div className="cr-timeline-step">
        <strong>第 {retest.months} 个月</strong>
        <span>复测时重点看：{focus}。</span>
      </div>
    </div>
  );
}
