import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReportView from "@/components/consumer/ReportView";
import type { ConsumerReport } from "@/lib/consumer-report";

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8")) as ConsumerReport;
const css = fs.readFileSync(process.argv[3], "utf8");
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>肠道菌群报告</title><style>${css}</style></head><body>${renderToStaticMarkup(<ReportView data={data} mode="internal" />)}</body></html>`;
fs.writeFileSync(process.argv[4], html);
