import type { Metadata } from "next";
import ReportPage from "@/components/consumer/ReportPage";
import "../../consumer/consumer-report.css";

export const metadata: Metadata = {
  title: "肠道菌群报告 | WGS·FMT",
  description: "面向消费者的肠道菌群网页报告，用于健康管理参考。",
};

export default async function ConsumerPreviewPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = await params;
  return <ReportPage sampleId={sampleId} mode="internal" />;
}
