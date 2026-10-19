/* Proxies page bridge calls to 127.0.0.1:8763. No other host is contacted. */
chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || !msg.bridge) return;
  var req = msg.bridge;
  var url = String(req.url || "");
  if (url.indexOf("http://127.0.0.1:8763/") !== 0) {
    sendResponse({ status: 400, body: "" });
    return;
  }
  var body = req.body;
  if (Array.isArray(body)) body = new Uint8Array(body);
  fetch(url, { method: req.method || "GET", body: body || undefined, cache: "no-store" })
    .then(function (res) { return res.text().then(function (text) { sendResponse({ status: res.status, body: text }); }); })
    .catch(function () { sendResponse({ status: 0, body: "" }); });
  return true;
});
