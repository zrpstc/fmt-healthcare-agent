"use client";

import { useEffect, useState } from "react";
import { buildNavItems, currentSectionFromEntries } from "@/lib/consumer-pure.mjs";
import type { Section } from "@/lib/consumer-report";

export default function SectionNav({ sections }: { sections: Section[] }) {
  const items = buildNavItems(sections);
  const [active, setActive] = useState(items[0]?.id || "");

  useEffect(() => {
    if (!items.length) return;
    const targets = items
      .map((item) => document.getElementById(item.id))
      .filter((element): element is HTMLElement => Boolean(element));
    if (!targets.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const next = currentSectionFromEntries(entries);
        if (next) setActive(next);
      },
      { rootMargin: "-18% 0px -55% 0px", threshold: [0.05, 0.18, 0.4] },
    );
    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [items]);

  return (
    <nav className="cr-nav" aria-label="报告目录">
      <div className="cr-nav-brand">WGS·FMT · 消费者版</div>
      <div className="cr-nav-list">
        {items.map((item) => (
          <a key={item.id} className={`cr-nav-link ${active === item.id ? "is-active" : ""}`} href={item.href}>
            {item.label}
          </a>
        ))}
      </div>
      <p className="cr-nav-note">手机上下滑阅读，目录会横向滚动并高亮当前部分。</p>
    </nav>
  );
}
