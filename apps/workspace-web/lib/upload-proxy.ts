/** Stream FASTQ multipart bodies without Next's external-rewrite body clone. */
export async function proxySampleUpload(request: Request): Promise<Response> {
  const contentType = request.headers.get("content-type") || "";
  if (!/^multipart\/form-data\s*;/i.test(contentType) || !request.body) {
    return Response.json({ detail: "请使用表单上传 FASTQ 文件。" }, { status: 415 });
  }
  const port = Number(process.env.WGS_API_PORT || "8503");
  const timeout = Number(process.env.WGS_WEB_PROXY_TIMEOUT_MS || "900000");
  if (!Number.isInteger(port) || port < 1 || port > 65535 ||
      !Number.isInteger(timeout) || timeout < 30000 || timeout > 1800000) {
    return Response.json({ detail: "上传服务配置无效，请联系管理员。" }, { status: 500 });
  }

  const headers = new Headers({ "content-type": contentType });
  for (const name of ["content-length", "authorization"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  request.signal.addEventListener("abort", abort, { once: true });
  if (request.signal.aborted) abort();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  try {
    // Keep the original boundary and stream; formData()/arrayBuffer() would
    // materialize sequencing files in the Web process. Node requires duplex.
    const init: RequestInit & { duplex: "half" } = {
      method: "POST", headers, body: request.body, duplex: "half",
      signal: controller.signal, cache: "no-store", redirect: "error",
    };
    const upstream = await fetch(`http://127.0.0.1:${port}/api/samples/upload`, init);
    // This endpoint returns only small job/error metadata, never FASTQ data.
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") || "application/json", "cache-control": "no-store" },
    });
  } catch (error) {
    if (request.signal.aborted) {
      return Response.json({ detail: "上传连接已取消。" }, { status: 499 });
    }
    if (timedOut) {
      return Response.json({ detail: "上传或提交超时，请先刷新样本列表确认任务是否已创建，再决定是否重试。" }, { status: 504 });
    }
    console.error("FASTQ upload proxy failed:", error instanceof Error ? error.message : "unknown error");
    return Response.json({ detail: "上传服务连接失败，请检查后端服务后重试。" }, { status: 502 });
  } finally {
    clearTimeout(timer);
    request.signal.removeEventListener("abort", abort);
  }
}
