"use client";

import type { ScatterBlock } from "@/lib/consumer-report";

export default function ScatterPlot({ block }: { block: ScatterBlock }) {
  const points = block.points;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const minX = Math.min(...xs, block.you[0]);
  const maxX = Math.max(...xs, block.you[0]);
  const minY = Math.min(...ys, block.you[1]);
  const maxY = Math.max(...ys, block.you[1]);
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(maxY - minY, 1e-9);
  const x = (value: number) => 10 + ((value - minX) / spanX) * 280;
  const y = (value: number) => 230 - ((value - minY) / spanY) * 210;
  return (
    <figure className="cr-scatter">
      <svg viewBox="0 0 300 250" role="img" aria-label={block.caption}>
        {points.map((point, index) => (
          <circle key={index} cx={x(point[0])} cy={y(point[1])} r="2.6" fill="#9DB5AE" opacity="0.55" />
        ))}
        <path
          d={`M ${x(block.you[0])} ${y(block.you[1]) - 7} L ${x(block.you[0]) + 7} ${y(block.you[1])} L ${x(block.you[0])} ${y(block.you[1]) + 7} L ${x(block.you[0]) - 7} ${y(block.you[1])} Z`}
          fill="#145C58"
        />
        <text x={x(block.you[0]) + 10} y={y(block.you[1]) - 8} fontSize="10" fill="#145C58" fontWeight="700">您</text>
      </svg>
      <figcaption>{block.caption}</figcaption>
    </figure>
  );
}
