"use client";

import type { HealthScore as HealthScoreType, Tone } from "@/lib/consumer-report";

const TONE_COLOR: Record<Tone, string> = {
  good: "#2E7150",
  neutral: "#45606A",
  watch: "#9A5410",
  consult: "#A63D2A",
};

function Gauge({ value, display, tone }: { value: number; display: string; tone: Tone }) {
  // 270° arc gauge; business number rendered from `display`, never recomputed.
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const arc = circumference * 0.75;
  const filled = arc * Math.max(0, Math.min(100, value)) / 100;
  return (
    <svg className="cr-score-gauge" viewBox="0 0 140 140" role="img" aria-label={`总体健康得分 ${display} 分`}>
      <g transform="rotate(135 70 70)">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="#ECE8E0" strokeWidth="12"
          strokeDasharray={`${arc} ${circumference}`} strokeLinecap="round" />
        <circle cx="70" cy="70" r={radius} fill="none" stroke={TONE_COLOR[tone]} strokeWidth="12"
          strokeDasharray={`${filled} ${circumference}`} strokeLinecap="round" />
      </g>
      <text x="70" y="74" textAnchor="middle" fontSize="34" fontWeight="800" fill="#1C2629">{display}</text>
      <text x="70" y="96" textAnchor="middle" fontSize="11" fill="#5A6468">满分100</text>
    </svg>
  );
}

export default function HealthScore({ score }: { score: HealthScoreType | null | undefined }) {
  if (!score) return null;
  return (
    <section className={`cr-score ${score.tone}`} aria-labelledby="cr-score-title">
      <div className="cr-score-main">
        <Gauge value={score.score.value ?? 0} display={score.score.display} tone={score.tone} />
        <div className="cr-score-head">
          <h3 id="cr-score-title">总体健康得分</h3>
          <span className={`cr-tag ${score.tone}`}>{score.grade}</span>
          <p>{score.text}</p>
        </div>
      </div>
      <ul className="cr-score-parts">
        {score.components.map((part) => (
          <li key={part.id}>
            <a href={part.anchor} className="cr-score-part-head">
              <span>{part.label}<em>权重{part.weight}%</em></span>
              <strong>{part.score.display}<small>分</small></strong>
            </a>
            <span className="cr-score-track" aria-hidden="true">
              <span style={{ width: `${Math.max(0, Math.min(100, part.score.value ?? 0))}%`, background: TONE_COLOR[part.tone] }} />
            </span>
            <p>{part.text}</p>
          </li>
        ))}
      </ul>
      <p className="cr-score-note">{score.note}</p>
    </section>
  );
}
