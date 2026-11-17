"use client";

import type { ScatterBlock } from "@/lib/consumer-report";

const GROUP_COLORS = ["#4C8DA6", "#C9853B", "#6E9F62", "#9A7BB0"];
const W = 340;
const H = 260;
const PAD = { left: 44, right: 12, top: 12, bottom: 38 };

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min;
  if (!(span > 0)) return [min];
  const raw = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => span / s <= count) ?? raw;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + 1e-9; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

export default function ScatterPlot({ block }: { block: ScatterBlock }) {
  const points = block.points;
  const you = block.you ?? null;
  const xs = points.map((point) => point[0]).concat(you ? [you[0]] : []);
  const ys = points.map((point) => point[1]).concat(you ? [you[1]] : []);
  let minX = Math.min(...xs);
  let maxX = Math.max(...xs);
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);
  if (block.diagonal) {
    // Shared scale so y = x is a true diagonal.
    minX = minY = Math.min(minX, minY);
    maxX = maxY = Math.max(maxX, maxY);
  }
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(maxY - minY, 1e-9);
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (value: number) => PAD.left + ((value - minX) / spanX) * plotW;
  const y = (value: number) => PAD.top + plotH - ((value - minY) / spanY) * plotH;
  const groups = block.groups ?? [];
  const showTicks = Boolean(block.x_label || block.y_label) && block.diagonal;
  const xTicks = showTicks ? niceTicks(minX, maxX) : [];
  const yTicks = showTicks ? niceTicks(minY, maxY) : [];
  return (
    <figure className="cr-scatter">
      {block.title && <div className="cr-chart-title">{block.title}</div>}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={block.caption}>
        <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="none" stroke="var(--cr-line)" />
        {xTicks.map((tick) => (
          <g key={`x${tick}`}>
            <line x1={x(tick)} x2={x(tick)} y1={PAD.top + plotH} y2={PAD.top + plotH + 4} stroke="#9AA4A8" />
            <text x={x(tick)} y={PAD.top + plotH + 15} fontSize="9" textAnchor="middle" fill="#5A6468">{tick}</text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line x1={PAD.left - 4} x2={PAD.left} y1={y(tick)} y2={y(tick)} stroke="#9AA4A8" />
            <text x={PAD.left - 6} y={y(tick) + 3} fontSize="9" textAnchor="end" fill="#5A6468">{tick}</text>
          </g>
        ))}
        {block.diagonal && (
          <line x1={x(minX)} y1={y(minX)} x2={x(maxX)} y2={y(maxX)} stroke="#7A8689" strokeDasharray="4 4" strokeWidth="1.2" />
        )}
        {points.map((point, index) => {
          const group = block.point_groups?.[index];
          const color = group !== undefined && groups.length ? GROUP_COLORS[group % GROUP_COLORS.length] : "#9DB5AE";
          return <circle key={index} cx={x(point[0])} cy={y(point[1])} r="2.4" fill={color} opacity="0.5" />;
        })}
        {you && (
          <>
            <path
              d={`M ${x(you[0])} ${y(you[1]) - 7} L ${x(you[0]) + 7} ${y(you[1])} L ${x(you[0])} ${y(you[1]) + 7} L ${x(you[0]) - 7} ${y(you[1])} Z`}
              fill="#145C58" stroke="#fff" strokeWidth="1.5"
            />
            <text x={x(you[0]) + 10} y={y(you[1]) - 8} fontSize="11" fill="#145C58" fontWeight="700">{block.you_label ?? "您"}</text>
          </>
        )}
        {block.x_label && (
          <text x={PAD.left + plotW / 2} y={H - 6} fontSize="10" textAnchor="middle" fill="#5A6468">{block.x_label}</text>
        )}
        {block.y_label && (
          <text x={12} y={PAD.top + plotH / 2} fontSize="10" textAnchor="middle" fill="#5A6468"
            transform={`rotate(-90 12 ${PAD.top + plotH / 2})`}>{block.y_label}</text>
        )}
      </svg>
      {groups.length > 0 && (
        <ul className="cr-scatter-legend">
          {groups.map((group, index) => (
            <li key={group.id}><span style={{ background: GROUP_COLORS[index % GROUP_COLORS.length] }} />{group.label}</li>
          ))}
          {you && <li><span className="you" />{block.you_label ?? "您"}</li>}
        </ul>
      )}
      <figcaption>{block.caption}</figcaption>
    </figure>
  );
}
