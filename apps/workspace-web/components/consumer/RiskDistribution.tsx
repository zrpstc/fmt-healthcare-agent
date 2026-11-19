"use client";

import { useMemo, useState, type MouseEvent } from "react";
import type { GlossaryEntry, RiskDistributionBlock, RiskLevel } from "@/lib/consumer-report";
import { RichText } from "./RichText";

// Validated categorical pair (light surface): healthy = teal, patients = orange.
const HEALTHY = "#0F8A70";
const PATIENTS = "#D9622B";
const LEVEL_TONE: Record<RiskLevel, "good" | "watch" | "consult"> = { low: "good", medium: "watch", high: "consult" };

const W = 640;
const H = 226;
const PAD_L = 14;
const PAD_R = 14;
const PLOT_TOP = 30;
const PLOT_BOTTOM = 172;
const BAND_TOP = 200;
const BAND_H = 22;

function niceTicks(lo: number, hi: number, count = 5): number[] {
  const span = hi - lo || 1;
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => span / s <= count) || power * 10;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}

function fmt(value: number) {
  const abs = Math.abs(value);
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 10) return value.toFixed(1).replace(/\.0$/, "");
  return value.toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
}

export default function RiskDistribution({ block, glossary }: { block: RiskDistributionBlock; glossary: GlossaryEntry[] }) {
  const [hoverX, setHoverX] = useState<number | null>(null);
  const lo = block.grid[0];
  const hi = block.grid[block.grid.length - 1];
  const x = (v: number) => PAD_L + ((v - lo) / (hi - lo || 1)) * (W - PAD_L - PAD_R);
  const invert = (px: number) => lo + ((px - PAD_L) / (W - PAD_L - PAD_R)) * (hi - lo);
  const peak = Math.max(...block.healthy, ...(block.patients || [0])) || 1;
  const y = (d: number) => PLOT_BOTTOM - (d / peak) * (PLOT_BOTTOM - PLOT_TOP);

  const paths = useMemo(() => {
    const build = (density: number[]) => {
      const line = density.map((d, i) => `${i ? "L" : "M"}${x(block.grid[i]).toFixed(1)},${y(d).toFixed(1)}`).join("");
      const area = `${line}L${x(hi).toFixed(1)},${PLOT_BOTTOM}L${x(lo).toFixed(1)},${PLOT_BOTTOM}Z`;
      return { line, area };
    };
    return { healthy: build(block.healthy), patients: block.patients ? build(block.patients) : null };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [block]);

  const youX = x(block.you);
  const ticks = niceTicks(lo, hi);
  const bandAt = (v: number) => block.bands.find((b) => v >= b.start && v <= b.end) || block.bands[block.bands.length - 1];
  const onMove = (event: MouseEvent<SVGRectElement>) => {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * W;
    setHoverX(Math.min(W - PAD_R, Math.max(PAD_L, px)));
  };
  const hoverValue = hoverX === null ? null : invert(hoverX);
  const tone = LEVEL_TONE[block.level];
  const youLabel = `您 ${block.score.display}`;
  const youAnchor = youX > W - 70 ? "end" : youX < 70 ? "start" : "middle";

  return (
    <figure className="cr-chart cr-risk">
      <div className="cr-risk-head">
        <figcaption className="cr-chart-title">{block.title}</figcaption>
        <span className={`cr-tag ${tone}`}>相对风险：{block.level_label}</span>
      </div>
      <p className="cr-risk-text"><RichText text={block.text} glossary={glossary} /></p>
      <div className="cr-risk-legend" aria-hidden="true">
        <span><i style={{ background: HEALTHY }} />{block.healthy_label}</span>
        {block.patients && <span><i style={{ background: PATIENTS }} />{block.patients_label}</span>}
        <span><b />您的位置</span>
      </div>
      <svg
        className="cr-risk-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${block.title}风险评分分布：${block.text}`}
      >
        {ticks.map((t) => (
          <line key={`g${t}`} x1={x(t)} x2={x(t)} y1={PLOT_TOP} y2={PLOT_BOTTOM} className="cr-risk-grid" />
        ))}
        <path d={paths.healthy.area} fill={HEALTHY} fillOpacity={0.16} />
        <path d={paths.healthy.line} fill="none" stroke={HEALTHY} strokeWidth={2} />
        {paths.patients && (
          <>
            <path d={paths.patients.area} fill={PATIENTS} fillOpacity={0.14} />
            <path d={paths.patients.line} fill="none" stroke={PATIENTS} strokeWidth={2} />
          </>
        )}
        <line x1={PAD_L} x2={W - PAD_R} y1={PLOT_BOTTOM} y2={PLOT_BOTTOM} className="cr-risk-axis" />
        {ticks.map((t) => (
          <text key={`t${t}`} x={x(t)} y={PLOT_BOTTOM + 15} textAnchor="middle" className="cr-risk-tick">{fmt(t)}</text>
        ))}
        {block.bands.map((band) => {
          const x0 = x(band.start);
          const x1 = x(band.end);
          const width = Math.max(0, x1 - x0 - 2);
          return (
            <g key={band.key}>
              <rect x={x0 + 1} y={BAND_TOP} width={width} height={BAND_H} rx={4} className={`cr-risk-band ${LEVEL_TONE[band.key]}`} />
              {width > 34 && (
                <text x={x0 + 1 + width / 2} y={BAND_TOP + 15} textAnchor="middle" className="cr-risk-band-label">{band.label}</text>
              )}
            </g>
          );
        })}
        <line x1={youX} x2={youX} y1={PLOT_TOP - 6} y2={BAND_TOP + BAND_H} className="cr-risk-you" />
        <text x={youX} y={PLOT_TOP - 12} textAnchor={youAnchor} className="cr-risk-you-label">{youLabel}</text>
        {hoverX !== null && hoverValue !== null && (
          <g pointerEvents="none" className="cr-risk-hover">
            <line x1={hoverX} x2={hoverX} y1={PLOT_TOP} y2={PLOT_BOTTOM} className="cr-risk-cross" />
            <g transform={`translate(${Math.min(hoverX + 8, W - 150)}, ${PLOT_TOP + 4})`}>
              <rect width={140} height={38} rx={6} className="cr-risk-tip" />
              <text x={8} y={16} className="cr-risk-tip-text">评分 {fmt(hoverValue)}</text>
              <text x={8} y={31} className="cr-risk-tip-sub">所在区间：{bandAt(hoverValue).label}</text>
            </g>
          </g>
        )}
        <rect
          x={PAD_L}
          y={PLOT_TOP - 20}
          width={W - PAD_L - PAD_R}
          height={BAND_TOP + BAND_H - PLOT_TOP + 20}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHoverX(null)}
        />
      </svg>
      <div className="cr-risk-axis-title">{block.x_label}（向右越高）</div>
      {block.drivers && block.drivers.length > 0 && (
        <p className="cr-risk-drivers">
          推高评分的主要菌群特征：
          {block.drivers.map((driver, index) => (
            <span key={driver}>{index ? "、" : ""}<RichText text={driver} glossary={glossary} /></span>
          ))}
        </p>
      )}
      {block.caption && <p className="cr-chart-caption">{block.caption}</p>}
    </figure>
  );
}
