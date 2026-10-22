export interface UploadProgress {
  loaded: number;
  total: number;
  percent: number;
  phase: "uploading" | "submitting";
}

export interface SampleUpload {
  sampleId: string;
  layout: "single" | "paired";
  read1: File;
  read2?: File | null;
  onProgress?: (progress: UploadProgress) => void;
}

export function uploadSampleFiles(value: SampleUpload): Promise<{ sample_id: string; state: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.set("sample_id", value.sampleId);
    form.set("layout", value.layout);
    form.set("read1", value.read1);
    if (value.layout === "paired" && value.read2) form.set("read2", value.read2);
    const xhr = new XMLHttpRequest();
    const fileBytes = value.read1.size + (value.layout === "paired" ? value.read2?.size || 0 : 0);
    xhr.open("POST", "/backend/api/samples/upload");
    xhr.timeout = 15 * 60 * 1000;
    const token = window.localStorage.getItem("wgs-auth-token");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    // The browser supplies Content-Type, including the multipart boundary.
    xhr.upload.onprogress = event => {
      const total = event.lengthComputable ? event.total : fileBytes;
      value.onProgress?.({ loaded: event.loaded, total, percent: total ? Math.min(100, Math.round(event.loaded * 100 / total)) : 0, phase: "uploading" });
    };
    xhr.upload.onload = () => value.onProgress?.({ loaded: fileBytes, total: fileBytes, percent: 100, phase: "submitting" });
    xhr.onload = () => {
      let payload: { detail?: unknown; sample_id?: string; state?: string } = {};
      try { payload = JSON.parse(xhr.responseText); } catch { /* HTTP status below gives a useful fallback. */ }
      if (xhr.status >= 200 && xhr.status < 300 && payload.sample_id && payload.state) {
        resolve({ sample_id: payload.sample_id, state: payload.state });
      } else {
        const fallback = xhr.status === 413 ? "上传文件超过服务器允许的大小，请联系管理员调整上传限制。" : `上传失败 (${xhr.status})，请检查服务状态后重试。`;
        reject(new Error(typeof payload.detail === "string" ? payload.detail : fallback));
      }
    };
    xhr.onerror = () => reject(new Error("上传连接中断，请先刷新样本列表确认任务是否已创建，再决定是否重试。"));
    xhr.ontimeout = () => reject(new Error("上传超过 15 分钟，请先刷新样本列表确认任务是否已创建，再决定是否重试。"));
    xhr.onabort = () => reject(new Error("上传已取消。"));
    xhr.send(form);
  });
}
