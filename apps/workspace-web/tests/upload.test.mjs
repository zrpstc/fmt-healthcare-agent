import assert from "node:assert/strict";
import { File } from "node:buffer";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { once } from "node:events";
import { test } from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../lib/${name}.ts`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const { proxySampleUpload } = await load("upload-proxy");
const { uploadSampleFiles } = await load("sample-upload");

test("stream more than 10 MiB intact, preserving boundary and auth, without forwarding cookies", async () => {
  const chunk = Buffer.alloc(65536, "A");
  const repeats = 384; // 24 MiB
  const expected = createHash("sha256");
  for (let n = 0; n < repeats; n++) expected.update(chunk);
  const server = createServer(async (req, res) => {
    const hash = createHash("sha256"); let bytes = 0;
    for await (const part of req) { hash.update(part); bytes += part.length; }
    res.writeHead(202, { "content-type": "application/json" });
    res.end(JSON.stringify({ bytes, hash: hash.digest("hex"), auth: req.headers.authorization,
      contentType: req.headers["content-type"], cookie: req.headers.cookie || null, url: req.url }));
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const old = process.env.WGS_API_PORT;
  process.env.WGS_API_PORT = String(server.address().port);
  try {
    let n = 0;
    const response = await proxySampleUpload(new Request("http://web/backend/api/samples/upload", {
      method: "POST", duplex: "half",
      headers: { "content-type": "multipart/form-data; boundary=original", "content-length": String(chunk.length * repeats), authorization: "Bearer synthetic-token", cookie: "do-not-forward=this" },
      body: new ReadableStream({ pull(controller) { if (n++ < repeats) controller.enqueue(chunk); else controller.close(); } }),
    }));
    assert.equal(response.status, 202);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), { bytes: chunk.length * repeats, hash: expected.digest("hex"),
      auth: "Bearer synthetic-token", contentType: "multipart/form-data; boundary=original", cookie: null, url: "/api/samples/upload" });
  } finally {
    if (old === undefined) delete process.env.WGS_API_PORT; else process.env.WGS_API_PORT = old;
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
});

const multipart = signal => new Request("http://web/backend/api/samples/upload", {
  method: "POST", headers: { "content-type": "multipart/form-data; boundary=synthetic" }, body: "synthetic", signal,
});

test("upstream validation errors retain status and detail", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "重复样本" }, { status: 409 }));
  const response = await proxySampleUpload(multipart());
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { detail: "重复样本" });
});

test("a non-multipart request is rejected before connecting upstream", async t => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw Error("must not call"); });
  assert.equal((await proxySampleUpload(new Request("http://web", { method: "POST", body: "invalid" }))).status, 415);
  assert.equal(fetch.mock.callCount(), 0);
});

test("upstream connection failures return a clear 502", async t => {
  t.mock.method(console, "error", () => {});
  t.mock.method(globalThis, "fetch", async () => { throw Error("connection refused"); });
  const response = await proxySampleUpload(multipart());
  assert.equal(response.status, 502);
  assert.match((await response.json()).detail, /连接失败/);
});

test("a disconnected client aborts the upstream request", async t => {
  const controller = new AbortController(); controller.abort();
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    assert.equal(init.signal.aborted, true); throw Error("aborted");
  });
  assert.equal((await proxySampleUpload(multipart(controller.signal))).status, 499);
});

test("a stalled upstream is aborted and returns 504", async t => {
  const original = globalThis.setTimeout;
  t.mock.method(globalThis, "setTimeout", callback => original(callback, 5));
  t.mock.method(globalThis, "fetch", (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(Error("aborted")), { once: true });
  }));
  const response = await proxySampleUpload(multipart());
  assert.equal(response.status, 504);
  assert.match((await response.json()).detail, /确认任务是否已创建/);
});

class FakeXHR {
  static latest;
  constructor() { FakeXHR.latest = this; this.upload = {}; this.headers = {}; }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(form) { this.form = form; }
}
function browser(t) {
  const oldXHR = globalThis.XMLHttpRequest, oldWindow = globalThis.window;
  globalThis.XMLHttpRequest = FakeXHR;
  globalThis.window = { localStorage: { getItem: () => "synthetic-token" } };
  t.after(() => { globalThis.XMLHttpRequest = oldXHR; globalThis.window = oldWindow; });
  return { sampleId: "synthetic", layout: "paired", read1: new File(["R1"], "r1.fastq"), read2: new File(["R2"], "r2.fastq") };
}

test("browser sends true pairs with auth and reports transfer then submission", async t => {
  const value = browser(t), progress = [];
  const promise = uploadSampleFiles({ ...value, onProgress: event => progress.push(event) });
  const xhr = FakeXHR.latest;
  assert.equal(xhr.url, "/backend/api/samples/upload");
  assert.equal(xhr.timeout, 900000);
  assert.deepEqual(xhr.headers, { Authorization: "Bearer synthetic-token" });
  assert.equal(xhr.form.get("read1").name, "r1.fastq");
  assert.equal(xhr.form.get("read2").name, "r2.fastq");
  xhr.upload.onprogress({ lengthComputable: true, loaded: 20, total: 100 });
  xhr.upload.onload();
  assert.equal(progress[0].percent, 20);
  assert.equal(progress[0].phase, "uploading");
  assert.equal(progress[1].phase, "submitting");
  xhr.status = 202; xhr.responseText = JSON.stringify({ sample_id: "synthetic", state: "running" }); xhr.onload();
  assert.deepEqual(await promise, { sample_id: "synthetic", state: "running" });
});

test("single-end submission does not send a previously selected mate", async t => {
  const promise = uploadSampleFiles({ ...browser(t), layout: "single" });
  const xhr = FakeXHR.latest;
  assert.equal(xhr.form.has("read2"), false);
  xhr.status = 202; xhr.responseText = JSON.stringify({ sample_id: "synthetic", state: "running" }); xhr.onload();
  await promise;
});

for (const [event, message] of [["ontimeout", /15 分钟/], ["onerror", /连接中断/], ["onabort", /已取消/]]) {
  test(`browser ${event} rejects instead of waiting forever`, async t => {
    const promise = uploadSampleFiles(browser(t));
    const result = assert.rejects(promise, message);
    FakeXHR.latest[event](); await result;
  });
}

test("browser handles non-JSON 413 errors", async t => {
  const promise = uploadSampleFiles(browser(t));
  const result = assert.rejects(promise, /超过服务器允许的大小/);
  const xhr = FakeXHR.latest; xhr.status = 413; xhr.responseText = "<html>too large</html>"; xhr.onload(); await result;
});

test("browser preserves backend rejection details", async t => {
  const promise = uploadSampleFiles(browser(t));
  const result = assert.rejects(promise, /重复样本/);
  const xhr = FakeXHR.latest; xhr.status = 409; xhr.responseText = JSON.stringify({ detail: "重复样本" }); xhr.onload(); await result;
});
