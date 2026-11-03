// 一致性测试：Worker 的密钥算法必须与 tools/dingai/core/edition.py 逐字节一致。
// 运行：node test-worker.js   （需要本机有 python3）
const { execFileSync } = require("child_process");
const crypto = require("crypto");
const path = require("path");

const SECRET = "dingcode-license-dev-secret-v1";

function issueKeyJs(edition, yyyymmdd) {
  const sig = crypto.createHmac("sha256", SECRET)
    .update(`DGA1|${edition}|${yyyymmdd}`)
    .digest().subarray(0, 8).toString("hex");
  return `DGA1-${edition}-${yyyymmdd}-${sig}`;
}

// worker.js 里的 Web Crypto 版本（用 Node 的 webcrypto 等价物抽出来测同一段代码）
async function issueKeyWorker(edition, yyyymmdd) {
  const key = await crypto.webcrypto.subtle.importKey(
    "raw", new TextEncoder().encode(SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.webcrypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(`DGA1|${edition}|${yyyymmdd}`)));
  let hex = "";
  for (let i = 0; i < 8; i++) hex += sig[i].toString(16).padStart(2, "0");
  return `DGA1-${edition}-${yyyymmdd}-${hex}`;
}

function issueKeyPy(edition, yyyymmdd) {
  const out = execFileSync("python3", ["-c",
    "import sys; sys.path.insert(0, '../tools/dingai'); from core import edition; print(edition.issue_key(sys.argv[1], sys.argv[2], sys.argv[3].encode()))",
    edition, yyyymmdd, SECRET], { cwd: __dirname }).toString().trim();
  return out;
}

(async () => {
  let failed = 0;
  for (const [edition, expires] of [["pro", "99991231"], ["team", "20301231"], ["pro", "20270101"]]) {
    const py = issueKeyPy(edition, expires);
    const js = issueKeyJs(edition, expires);
    const wk = await issueKeyWorker(edition, expires);
    const ok = py === js && js === wk;
    console.log(`${ok ? "ok " : "FAIL"} ${edition} ${expires}  py=${py}  js=${js}  worker=${wk}`);
    if (!ok) failed++;
  }
  // Python 侧必须能验证 Worker 签出的密钥
  for (const [edition, expires] of [["pro", "99991231"]]) {
    const wk = await issueKeyWorker(edition, expires);
    const parsed = execFileSync("python3", ["-c",
      "import sys; sys.path.insert(0, '../tools/dingai'); from core import edition; print(edition.parse_key(sys.argv[1]))",
      wk], { cwd: __dirname }).toString().trim();
    const ok = parsed === `('${edition}', '${expires}')`;
    console.log(`${ok ? "ok " : "FAIL"} python parses worker key -> ${parsed}`);
    if (!ok) failed++;
  }
  if (failed) { console.error(`${failed} mismatches`); process.exit(1); }
  console.log("ALL CONSISTENT");
})();
