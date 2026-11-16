"use client";

import type { ConsumerReport, GlossaryEntry } from "@/lib/consumer-report";
import ReportTable from "./ReportTable";

export default function LearnMore({ report }: { report: ConsumerReport }) {
  const glossary: GlossaryEntry[] = report.glossary;
  return (
    <div className="cr-learn">
      <details>
        <summary>术语表</summary>
        <div className="cr-learn-body">
          <ReportTable block={{ type: "table", columns: ["术语", "解释"], rows: report.glossary.map((entry) => [entry.name, entry.text]) }} glossary={glossary} />
        </div>
      </details>
      <details>
        <summary>方法与参考人群</summary>
        <div className="cr-learn-body">
          {report.methods.map((method) => (
            <div key={method.title} style={{ marginBottom: 14 }}>
              <h4 style={{ margin: "0 0 4px", fontSize: 14 }}>{method.title}</h4>
              <p style={{ margin: 0, fontSize: 13, color: "var(--cr-sub)" }}>{method.body}</p>
            </div>
          ))}
        </div>
      </details>
      <details>
        <summary>本次未包含的项目</summary>
        <div className="cr-learn-body">
          {report.omissions.length ? (
            <ReportTable
              block={{
                type: "table",
                columns: ["部分", "项目", "原因"],
                rows: report.omissions.map((row) => [row.section, row.item, row.reason]),
                footnote: "未包含不代表正常或异常。",
              }}
              glossary={glossary}
            />
          ) : <p style={{ fontSize: 13, color: "var(--cr-sub)" }}>没有需要特别列出的项目。</p>}
        </div>
      </details>
      <details>
        <summary>参考文献</summary>
        <div className="cr-learn-body">
          {report.references.length ? (
            <ReportTable
              block={{
                type: "table",
                columns: ["编号", "标题", "年份", "DOI/链接"],
                rows: report.references.map((ref) => [ref.id, ref.title, ref.year ? String(ref.year) : "", ref.doi || ref.url || ""]),
              }}
              glossary={glossary}
            />
          ) : <p style={{ fontSize: 13, color: "var(--cr-sub)" }}>正文与子图没有引用可列出的文献。</p>}
        </div>
      </details>
      <details>
        <summary>数据下载</summary>
        <div className="cr-learn-body">
          {report.downloads.length ? (
            <div className="cr-downloads">
              {report.downloads.map((item) => (
                <div className="cr-download" key={item.kind}>
                  <span>{item.label}</span>
                  <a href={item.href}>下载</a>
                </div>
              ))}
            </div>
          ) : <p style={{ fontSize: 13, color: "var(--cr-sub)" }}>当前没有可下载的文件。</p>}
        </div>
      </details>
    </div>
  );
}
