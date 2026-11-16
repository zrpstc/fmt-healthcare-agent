"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, ExternalLink, ShieldCheck, X } from "lucide-react";
import { api, AuthUser } from "@/lib/api";
import type { ReviewEntry } from "@/lib/consumer-report";

export default function ReviewPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [entries, setEntries] = useState<ReviewEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage("");
    try {
      const result = await api.glossaryReview();
      setEntries(result.entries);
      setTexts(Object.fromEntries(result.entries.map((entry) => [entry.term_id, entry.generated_text])));
    } catch (error) {
      setMessage((error as Error).message);
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
      } else {
        void load();
      }
    }).catch(() => {
      window.localStorage.removeItem("wgs-auth-token");
      setLoading(false);
    });
  }, []);

  const review = async (termId: string, field: "one_liner" | "watch_note", status: "approved" | "rejected", text: string) => {
    setBusy(true);
    setMessage("");
    try {
      await api.reviewGlossary(termId, field, status, text);
      setEntries((current) => current.filter((entry) => entry.term_id !== termId));
      setSelected((current) => {
        const next = new Set(current);
        next.delete(termId);
        return next;
      });
      setMessage(status === "approved" ? "已通过并写入审核记录。" : "已拒绝，正文不会显示该解释。");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const batchApprove = async () => {
    if (!selected.size) return;
    setBusy(true);
    try {
      for (const termId of selected) {
        const entry = entries.find((item) => item.term_id === termId);
        if (!entry) continue;
        await api.reviewGlossary(termId, entry.field, "approved", texts[termId] || entry.generated_text);
      }
      setEntries((current) => current.filter((entry) => !selected.has(entry.term_id)));
      setSelected(new Set());
      setMessage("批量通过完成。");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!user) {
    return (
      <div className="panel" style={{ padding: 24 }}>
        <h1 style={{ margin: 0 }}>术语与说明审核台</h1>
        <p style={{ color: "var(--muted)" }}>请先登录。审核仅对管理员或研究者开放。</p>
        <Link className="button button-primary" href="/reports?auth=login">登录</Link>
      </div>
    );
  }
  if (user.role === "viewer") {
    return <div className="panel" style={{ padding: 24 }}><h1 style={{ margin: 0 }}>无权访问</h1><p style={{ color: "var(--muted)" }}>审核台只对管理员或研究者开放。</p></div>;
  }

  return (
    <>
      <div className="page-intro">
        <div><p className="eyebrow">Glossary review</p><h1>术语与说明审核台</h1><p>待审条目不会进入公开分享页；通过后才会在正文中显示解释。</p></div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="button button-ghost" onClick={() => void load()} disabled={loading || busy}>刷新</button>
          <button className="button button-primary" onClick={batchApprove} disabled={!selected.size || busy}><ShieldCheck size={15}/>批量通过</button>
        </div>
      </div>
      {message && <div className={message.startsWith("已") || message.includes("完成") ? "notice" : "error-banner"}>{message}</div>}
      {loading ? <div className="panel" style={{ padding: 22 }}>正在读取审核队列…</div> : (
        <div style={{ display: "grid", gap: 12 }}>
          {entries.map((entry) => (
            <article className="panel" key={entry.term_id} style={{ padding: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 15 }}>{entry.name} <small style={{ color: "var(--muted)" }}>{entry.term_id}</small></h2>
                  <p style={{ margin: "5px 0", color: "var(--muted)", fontSize: 11 }}>字段：{entry.field} · 来源：{entry.model || "人工草稿"} · 样本：{entry.samples_used.join("、") || "暂无"}</p>
                </div>
                <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11 }}>
                  <input type="checkbox" checked={selected.has(entry.term_id)} onChange={(event) => {
                    setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(entry.term_id); else next.delete(entry.term_id);
                      return next;
                    });
                  }} /> 选择
                </label>
              </div>
              <textarea className="textarea" value={texts[entry.term_id] || ""} onChange={(event) => setTexts((current) => ({ ...current, [entry.term_id]: event.target.value }))} style={{ minHeight: 80, marginTop: 8 }} />
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button className="button button-primary" disabled={busy} onClick={() => review(entry.term_id, entry.field, "approved", texts[entry.term_id] || entry.generated_text)}><Check size={14}/>通过</button>
                <button className="button button-ghost" disabled={busy} onClick={() => review(entry.term_id, entry.field, "rejected", "")}><X size={14}/>拒绝</button>
                {entry.sources.map((source, index) => (
                  source.id_or_url && source.id_or_url.startsWith("http") ? (
                    <a key={`${source.id_or_url}-${index}`} href={source.id_or_url} target="_blank" rel="noreferrer" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                      <ExternalLink size={12} />{source.title || source.id_or_url}
                    </a>
                  ) : (
                    <span key={`${source.title}-${index}`} style={{ fontSize: 11, color: "var(--muted)" }}>{source.title || source.id_or_url}</span>
                  )
                ))}
              </div>
            </article>
          ))}
          {!entries.length && <div className="panel" style={{ padding: 22 }}>当前没有待审条目。</div>}
        </div>
      )}
    </>
  );
}
