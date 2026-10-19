/* Injects the page script in the main world and relays bridge calls to the service worker. */
(function () {
  document.addEventListener("dingai-bridge", function (ev) {
    var detail = ev.detail || {};
    function send(body) {
      chrome.runtime.sendMessage({
        bridge: { id: detail.id, url: detail.url, method: detail.method || "GET", body: body }
      }, function (resp) {
        document.dispatchEvent(new CustomEvent("dingai-bridge-result", {
          detail: { id: detail.id, status: resp && resp.status, body: resp && resp.body }
        }));
      });
    }
    var body = detail.body;
    if (body && typeof body.arrayBuffer === "function") {
      body.arrayBuffer().then(function (buf) { send(Array.from(new Uint8Array(buf))); }).catch(function () { send(""); });
    } else {
      send(body || "");
    }
  });

  var prelude = document.createElement("script");
  prelude.textContent = [
    "window.DINGAI_BRIDGE_FETCH = function (url, options) {",
    "  options = options || {};",
    "  return new Promise(function (resolve) {",
    "    var id = Math.random().toString(36).slice(2);",
    "    function done(ev) {",
    "      if (!ev.detail || ev.detail.id !== id) return;",
    "      document.removeEventListener('dingai-bridge-result', done);",
    "      var body = ev.detail.body || '';",
    "      resolve({ ok: (ev.detail.status || 0) >= 200 && (ev.detail.status || 0) < 300, status: ev.detail.status || 0,",
    "        text: function () { return Promise.resolve(body); },",
    "        json: function () { try { return Promise.resolve(JSON.parse(body)); } catch (e) { return Promise.resolve(null); } } });",
    "    }",
    "    document.addEventListener('dingai-bridge-result', done);",
    "    document.dispatchEvent(new CustomEvent('dingai-bridge', { detail: { id: id, url: url, method: options.method || 'GET', body: options.body || '' } }));",
    "  });",
    "};"
  ].join("\n");
  (document.documentElement || document.head).appendChild(prelude);
  prelude.remove();

  var page = document.createElement("script");
  page.async = false;
  page.src = chrome.runtime.getURL("anno.js");
  (document.documentElement || document.head).appendChild(page);
})();
