"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ConsumerReport } from "@/lib/consumer-report";
import ReportView from "./ReportView";

export default function ReportPage({
  sampleId,
  token,
  mode,
}: {
  sampleId?: string;
  token?: string;
  mode: "internal" | "public";
}) {
  const [data, setData] = useState<ConsumerReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = mode === "internal" && sampleId
        ? await api.consumerReport(sampleId)
        : await api.shareReport(token || "");
      setData(result);
    } catch (cause) {
      const message = (cause as Error).message;
      setError(mode === "public" ? "链接无效、已过期或报告暂不可用。" : message || "报告读取失败。");
    } finally {
      setLoading(false);
    }
  }, [mode, sampleId, token]);

  useEffect(() => { void load(); }, [load, attempt]);

  if (loading) {
    return (
      <div className="cr-root">
        <div className="cr-loading" aria-busy="true" aria-label="正在加载报告">
          <div className="cr-skeleton" />
          <div className="cr-skeleton short" />
          <div className="cr-skeleton" />
          <div className="cr-skeleton short" />
        </div>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="cr-root">
        <div className="cr-error" role="alert">
          <h2>{mode === "public" ? "这个链接暂时不能打开" : "消费者版报告暂不可用"}</h2>
          <p>{error || "请稍后重试。"}</p>
          <button type="button" className="cr-button" onClick={() => setAttempt((value) => value + 1)}>重试</button>
        </div>
      </div>
    );
  }
  return <ReportView data={data} mode={mode} />;
}
