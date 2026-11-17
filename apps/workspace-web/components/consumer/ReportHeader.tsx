"use client";

import { Printer } from "lucide-react";
import type { SampleMeta } from "@/lib/consumer-report";

export function printReport() {
  document.querySelectorAll<HTMLDetailsElement>(".cr-learn details").forEach((detail) => { detail.open = true; });
  window.print();
}

export function PrintButton() {
  return (
    <button type="button" className="cr-print-button" onClick={printReport} aria-label="下载或打印消费者版 PDF">
      <Printer size={16} /> 下载 PDF
    </button>
  );
}

export default function ReportHeader({ sample, mode }: { sample: SampleMeta; mode: "internal" | "public" }) {
  return (
    <header className="cr-header">
      <div>
        <div className="cr-brand">WGS·FMT 肠道菌群报告</div>
        <h1>肠道菌群报告</h1>
        <p>本报告用于健康管理参考，不用于疾病诊断。</p>
      </div>
      <div style={{ display: "grid", gap: 10, justifyItems: "end" }}>
        <div className="cr-header-meta">
          <span>样本：{sample.alias}</span>
          <span>检测日期：{sample.report_date}</span>
          <span>报告版本：{sample.builder_version}</span>
        </div>
        {mode === "internal" && <PrintButton />}
        {mode === "public" && (
          <button type="button" className="cr-print-button" onClick={printReport} aria-label="打印消费者版报告">
            <Printer size={16} /> 打印
          </button>
        )}
      </div>
    </header>
  );
}
