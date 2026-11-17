"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, ExternalLink, RefreshCw, ShieldCheck, Sparkles, X } from "lucide-react";
import { api, AuthUser, ReportRow } from "@/lib/api";
import type { ReviewEntry } from "@/lib/consumer-report";

const keyOf = (entry: Pick<ReviewEntry, "term_id" | "field">) => `${entry.term_id}::${entry.field}`;
const FIELD_LABEL: Record<string, string> = { one_liner: "一句话说明", watch_note: "需留意说明" };
const SCOPE_LABEL: Record<string, string> = { species: "物种级", strain: "菌株级", genus: "同属" };
const STATUS_LABEL: Record<string, string> = {
  drafted: "已生成草稿", no_model: "未配置模型，仅收集证据", no_evidence: "没有找到证据",
  model_error: "模型调用失败", created: "新增", refreshed: "已更新证据", kept: "保留原草稿",
};

export default function ReviewPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [entries, setEntries] = useState<ReviewEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [includeRejected, setIncludeRejected] = useState(false);
  const [samples, setSamples] = useState<ReportRow[]>([]);
  const [sampleId, setSampleId] = useState("");

  const load = async (withRejected = includeRejected) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.glossaryReview(withRejected);
      setEntries(result.entries);
      setTexts(Object.fromEntries(result.entries.map((entry) => [keyOf(entry), entry.generated_text])));
      setSelected(new Set());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!window.localStorage.getItem("wgs-auth-token")) {
      setLoading(false);
      return;
    }
    api.me().then((value) => {
      setUser(value);
      if (value.role === "viewer") {
        setLoading(false);
        return;
      }
      void load(false);
      api.reports("").then((data) => {
        const ready = data.reports.filter((item) => item.artifacts.structured?.exists);
        setSamples(ready);
        setSampleId((current) => current || ready[0]?.sample_id || "");
      }).catch(() => setSamples([]));
    }).catch(() => {
      window.localStorage.removeItem("wgs-auth-token");
      setLoading(false);
    });
  }, []);

  const pendingCount = useMemo(() => entries.filter((entry) => entry.status !== "rejected").length, [entries]);

  const removeEntry = (key: string) => {
    setEntries((current) => current.filter((entry) => keyOf(entry) !== key));
    setSelected((current) => {
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  };

  const review = async (entry: ReviewEntry, status: "approved" | "rejected") => {
    const key = keyOf(entry);
    const text = (texts[key] || "").trim();
    if (status === "approved" && !text) {
      setError("通过前需要填写解释文字。");
      return;
    }
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await api.reviewGlossary(entry.term_id, entry.field, status, status === "approved" ? text : "");
      if (status === "approved" || !includeRejected) {
        removeEntry(key);
      } else {
        setEntries((current) => current.map((item) => keyOf(item) === key ? { ...item, status: "rejected" } : item));
      }
      setMessage(status === "approved" ? `已通过「${entry.name}」，下一次构建报告时生效。` : `已拒绝「${entry.name}」，正文不会显示这条解释。`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const batchApprove = async () => {
    const chosen = entries.filter((entry) => selected.has(keyOf(entry)) && (texts[keyOf(entry)] || "").trim());
    if (!chosen.length) return;
    setBusy(true);
    setMessage("");
    setError("");
    let done = 0;
    try {
      for (const entry of chosen) {
        await api.reviewGlossary(entry.term_id, entry.field, "approved", (texts[keyOf(entry)] || "").trim());
        removeEntry(keyOf(entry));
        done += 1;
      }
      setMessage(`已批量通过 ${done} 条。`);
    } catch (e) {
      setError(`已通过 ${done} 条后出错：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!sampleId) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api.generateGlossary(sampleId, 30, true);
      const parts = Object.entries(result.draft_status).map(([status, count]) => `${STATUS_LABEL[status] || status} ${count}`);
      setMessage(result.needs
        ? `样本 ${result.sample_id}：发现 ${result.needs} 条缺少解释的菌，处理 ${result.processed} 条${parts.length ? `（${parts.join("，")}）` : ""}。草稿已进入下方待审列表。`
        : `样本 ${result.sample_id} 中正文展示的菌都已有解释或已在待审列表中。`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!user) {
    return (
      <div className="panel" style={{ padding: 24 }}>
        <h1 style={{ margin: 0 }}>术语与说明审核台</h1>
        <p style={{ color: "var(--muted)" }}>请先登录。审核仅对管理员或研究者开放。</p>
        <Link className="button button-primary" href="/reports/review?auth=login">登录</Link>
      </div>
    );
  }
  if (user.role === "viewer") {
    return <div className="panel" style={{ padding: 24 }}><h1 style={{ margin: 0 }}>无权访问</h1><p style={{ color: "var(--muted)" }}>审核台只对管理员或研究者开放。</p></div>;
  }

  const selectable = entries.filter((entry) => entry.status !== "rejected" && (texts[keyOf(entry)] || "").trim());

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Glossary review</p>
          <h1>术语与说明审核台</h1>
          <p>消费者版报告里的菌种说明和概念解释，只有在这里通过后才会显示；公开分享页永远不显示待审内容。</p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="button button-ghost" onClick={() => void load()} disabled={loading || busy}><RefreshCw size={14}/>刷新</button>
          <button className="button button-primary" onClick={batchApprove} disabled={!selected.size || busy}><ShieldCheck size={15}/>批量通过（{selected.size}）</button>
        </div>
      </div>

      <section className="panel review-toolbar">
        <div>
          <strong>为样本补全解释</strong>
          <span>找出该样本报告正文中还没有解释的菌，收集文献证据并生成草稿（需在平台配置报告模型；未配置时只收集证据，由你撰写）。</span>
        </div>
        <label className="review-toolbar-field">
          <span>样本</span>
          <select className="select" value={sampleId} onChange={(e) => setSampleId(e.target.value)} disabled={busy || !samples.length}>
            {samples.map((item) => <option key={item.sample_id} value={item.sample_id}>{item.name && item.name !== item.sample_id ? `${item.name}（${item.sample_id}）` : item.sample_id}</option>)}
            {!samples.length && <option value="">暂无已生成报告的样本</option>}
          </select>
        </label>
        <button className="button button-coral" onClick={generate} disabled={busy || !sampleId}><Sparkles size={14}/>{busy ? "处理中…" : "补全解释"}</button>
        <label className="review-toolbar-check">
          <input type="checkbox" checked={includeRejected} onChange={(e) => { setIncludeRejected(e.target.checked); void load(e.target.checked); }}/>
          显示已拒绝
        </label>
      </section>

      {message && <div className="notice">{message}</div>}
      {error && <div className="error-banner">{error}</div>}

      {loading ? <div className="panel" style={{ padding: 22 }}>正在读取审核队列…</div> : (
        <div style={{ display: "grid", gap: 12 }}>
          {entries.length > 0 && (
            <div className="review-summary">
              <span>待审 {pendingCount} 条</span>
              <button className="button button-ghost" disabled={!selectable.length || busy}
                onClick={() => setSelected(new Set(selectable.map(keyOf)))}>全选可通过的条目</button>
            </div>
          )}
          {entries.map((entry) => {
            const key = keyOf(entry);
            const text = texts[key] || "";
            const rejected = entry.status === "rejected";
            return (
              <article className={`panel review-card ${rejected ? "is-rejected" : ""}`} key={key}>
                <div className="review-card-head">
                  <div>
                    <h2>{entry.name}{entry.latin && <em> {entry.latin}</em>}</h2>
                    <div className="review-tags">
                      <span className="pill">{FIELD_LABEL[entry.field] || entry.field}</span>
                      <span className="pill">{entry.origin === "candidate" ? "机器草稿" : "人工词条"}</span>
                      {entry.evidence_scope && <span className="pill">{SCOPE_LABEL[entry.evidence_scope] || entry.evidence_scope}证据</span>}
                      {entry.needs_writing && <span className="pill confirm">需人工撰写</span>}
                      {rejected && <span className="pill sensitive">已拒绝</span>}
                    </div>
                    <p className="review-meta">{entry.term_id} · 用到的样本：{entry.samples_used.join("、") || "暂无"}{entry.model ? ` · 来源：${entry.model}` : ""}</p>
                  </div>
                  {!rejected && (
                    <label className="review-select">
                      <input type="checkbox" disabled={!text.trim()} checked={selected.has(key)} onChange={(e) => {
                        setSelected((current) => {
                          const next = new Set(current);
                          if (e.target.checked) next.add(key); else next.delete(key);
                          return next;
                        });
                      }}/> 选择
                    </label>
                  )}
                </div>
                <textarea className="textarea" value={text} placeholder={entry.needs_writing ? "根据下方证据写一句话（一句话说明不超过40字，需留意说明不超过60字）" : ""}
                  onChange={(e) => setTexts((current) => ({ ...current, [key]: e.target.value }))} style={{ minHeight: 72, marginTop: 8 }}/>
                <div className="review-count">{text.trim().length} 字</div>
                {entry.evidence.length > 0 && (
                  <details className="review-evidence">
                    <summary>查看证据（{entry.evidence.length} 条）</summary>
                    <ol>
                      {entry.evidence.map((item, index) => (
                        <li key={`${item.id || index}`}>
                          <span>{item.sentence}</span>
                          <small>
                            {[item.source, item.scope ? (SCOPE_LABEL[item.scope] || item.scope) : "", item.title, item.year ? String(item.year) : ""].filter(Boolean).join(" · ")}
                            {item.url && item.url.startsWith("http") && <> · <a href={item.url} target="_blank" rel="noreferrer">原文<ExternalLink size={11}/></a></>}
                          </small>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                <div className="review-actions">
                  <button className="button button-primary" disabled={busy || !text.trim()} onClick={() => review(entry, "approved")}><Check size={14}/>{rejected ? "改为通过" : "通过"}</button>
                  {!rejected && <button className="button button-ghost" disabled={busy} onClick={() => review(entry, "rejected")}><X size={14}/>拒绝</button>}
                  {entry.sources.map((source, index) => (
                    source.id_or_url && source.id_or_url.startsWith("http") ? (
                      <a key={`${source.id_or_url}-${index}`} href={source.id_or_url} target="_blank" rel="noreferrer" className="review-source">
                        <ExternalLink size={12}/>{source.title || source.id_or_url}
                      </a>
                    ) : (
                      <span key={`${source.title}-${index}`} className="review-source muted">{source.title || source.id_or_url}</span>
                    )
                  ))}
                </div>
              </article>
            );
          })}
          {!entries.length && <div className="panel" style={{ padding: 22 }}>当前没有待审条目。可以在上方选择样本，为它补全缺少的解释。</div>}
        </div>
      )}
    </>
  );
}
