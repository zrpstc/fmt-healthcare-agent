"use client";

import { useEffect, useState } from "react";
import { Copy, Link2, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ShareLink } from "@/lib/consumer-report";

export default function ShareDialog({
  sampleId,
  sampleName,
  onClose,
}: {
  sampleId: string;
  sampleName: string;
  onClose: () => void;
}) {
  const [expiresDays, setExpiresDays] = useState(30);
  const [shares, setShares] = useState<ShareLink[]>([]);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.consumerShares(sampleId)
      .then((result) => setShares(result.shares))
      .catch((error: Error) => setMessage(error.message));
  }, [sampleId]);

  const create = async () => {
    setBusy(true);
    setMessage("");
    try {
      const result = await api.createConsumerShare(sampleId, expiresDays);
      setToken(result.token);
      setShares((current) => [
        ...current,
        { id: result.id, created_at: new Date().toISOString(), expires_at: result.expires_at, revoked_at: null, last_accessed_at: null },
      ]);
      setMessage("链接已生成。请复制后发给用户，链接本身即可访问。");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!token) return;
    const url = `${window.location.origin}/share/${token}`;
    try {
      await navigator.clipboard.writeText(url);
      setMessage("已复制分享链接。");
    } catch {
      setMessage(url);
    }
  };

  const revoke = async (id: string) => {
    setBusy(true);
    setMessage("");
    try {
      await api.revokeConsumerShare(sampleId, id);
      setShares((current) => current.map((item) => item.id === id ? { ...item, revoked_at: new Date().toISOString() } : item));
      setMessage("链接已撤销。");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cr-dialog-backdrop" role="dialog" aria-modal="true" aria-label="分享给用户">
      <div className="cr-dialog">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0 }}>分享给用户 · {sampleName}</h2>
          <button type="button" className="cr-button" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        <p style={{ fontSize: 13, color: "var(--cr-sub)" }}>公开页只显示消费者版，样本编号会换成别名；页面含 noindex 响应头。</p>
        <div className="cr-field">
          <label htmlFor="share-expiry">有效期（天）</label>
          <select id="share-expiry" value={expiresDays} onChange={(event) => setExpiresDays(Number(event.target.value))}>
            <option value={1}>1 天</option>
            <option value={7}>7 天</option>
            <option value={30}>30 天</option>
            <option value={90}>90 天</option>
          </select>
        </div>
        <div className="cr-dialog-actions">
          <button type="button" className="cr-button primary" onClick={create} disabled={busy}>
            <Link2 size={16} /> 生成链接
          </button>
          {token && <button type="button" className="cr-button" onClick={copy}><Copy size={16} /> 复制</button>}
        </div>
        {message && <p style={{ fontSize: 13, color: "var(--cr-brand)" }}>{message}</p>}
        <table>
          <thead><tr><th>创建时间</th><th>有效期</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {shares.map((share) => {
              const revoked = Boolean(share.revoked_at);
              return (
                <tr key={share.id}>
                  <td>{new Date(share.created_at).toLocaleString("zh-CN")}</td>
                  <td>{new Date(share.expires_at).toLocaleString("zh-CN")}</td>
                  <td>{revoked ? "已撤销" : "有效"}</td>
                  <td>
                    <button type="button" className="cr-button" onClick={() => revoke(share.id)} disabled={busy || revoked} aria-label="撤销链接">
                      <Trash2 size={14} /> 撤销
                    </button>
                  </td>
                </tr>
              );
            })}
            {!shares.length && <tr><td colSpan={4} style={{ color: "var(--cr-sub)" }}>还没有分享链接。</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
