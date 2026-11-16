import type { Metadata } from "next";
import ReportPage from "@/components/consumer/ReportPage";
import "../../consumer/consumer-report.css";

export const metadata: Metadata = {
  title: "肠道菌群报告",
  description: "面向消费者的肠道菌群网页报告，用于健康管理参考。",
  robots: { index: false, follow: false },
};

export default async function SharedReportPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <ReportPage token={token} mode="public" />;
}
