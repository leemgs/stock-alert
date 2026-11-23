/* Stock Alert — 간단 접속 코드 게이트 (initAuth / unlock)
 *
 * 초대받은 사용자를 위한 정보 공간임을 알리고, 접속 코드를 아는 사람만 화면을 보게 하는 "간단한 접근 제한"입니다.
 *
 *  - docs/config/access.json 에는 접속 코드의 SHA-256 해시(digest)와 version 만 저장합니다(평문 금지).
 *    digest 는 문자열 1개 또는 배열(접속 코드 여러 개)입니다.
 *  - 입력한 코드를 브라우저에서 SHA-256 으로 해시해 digest 와 비교하고, 일치하면 sessionStorage 에
 *    접근 허용 상태를 기록합니다(탭/브라우저를 닫으면 사라짐).
 *  - 설정(access.json)을 읽지 못하면 열어 주지 않습니다(fail-closed).
 *
 * ⚠️ 정적 사이트의 간단한 접근 제한이며, 민감정보 보호 목적이 아닙니다.
 *    해시와 페이지 데이터(docs/data/*.json)가 클라이언트에 그대로 노출되므로 진짜 보안 경계로 사용하지 마세요.
 *
 * 공개 API (전역): initAuth(), unlock(code), lockSite()
 */
(function () {
  "use strict";

  var SS_KEY = "stockalert.access";          // sessionStorage: 접근 허용 상태 {v, d}
  var SS_FAIL = "stockalert.access.fail";    // sessionStorage: 연속 실패 횟수
  var SS_UNTIL = "stockalert.access.until";  // sessionStorage: 재시도 가능 시각(ms)
  var MAX_FREE_TRIES = 5;                    // 이후 실패마다 대기 시간(초)이 2배씩 늘어남 (최대 60초)

  var SCRIPT_SRC = (document.currentScript && document.currentScript.src) || "";
  // 페이지 경로와 무관하게 스크립트 위치(…/assets/site.js) 기준으로 설정 파일을 찾는다.
  var CONFIG_URL = SCRIPT_SRC ? new URL("../config/access.json", SCRIPT_SRC).href : "config/access.json";

  var root = document.documentElement;
  var cfg = null;          // 로드된 access.json
  var initPromise = null;  // initAuth() 는 한 번만 수행
  var waiters = [];        // 잠금 해제를 기다리는 resolve 콜백

  /* 인증 전에는 본문을 숨겨 내용이 잠깐 보이는 깜빡임을 막는다. (스크립트는 <head> 에서 동기 로드) */
  root.classList.add("access-locked");
  try {   // 저장된 테마를 게이트 화면에도 즉시 적용
    var th = localStorage.getItem("stockalert.theme");
    if (th === "dark" || th === "light") root.setAttribute("data-theme", th);
  } catch (_) {}

  var style = document.createElement("style");
  style.textContent =
    "html.access-locked body>*:not(#accessGate){display:none!important}" +
    "#accessGate{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;" +
    "background:var(--page,#f9f9f7);color:var(--text-primary,#0b0b0b);" +
    "font-family:system-ui,-apple-system,'Segoe UI','Malgun Gothic','Apple SD Gothic Neo',sans-serif}" +
    "#accessGate form{width:100%;max-width:360px;background:var(--surface-1,#fcfcfb);border:1px solid var(--border,rgba(11,11,11,.1));" +
    "border-radius:16px;padding:26px 24px 20px;box-shadow:var(--shadow,0 4px 16px rgba(11,11,11,.08))}" +
    "#accessGate .ag-brand{display:flex;align-items:center;gap:10px;margin-bottom:6px}" +
    "#accessGate .ag-dot{width:11px;height:11px;border-radius:50%;background:var(--up,#d03b3b);" +
    "box-shadow:0 0 0 4px color-mix(in srgb,var(--up,#d03b3b) 22%,transparent)}" +
    "#accessGate h1{font-size:19px;margin:0;letter-spacing:-.01em}" +
    "#accessGate p{margin:6px 0 16px;font-size:13px;line-height:1.55;color:var(--text-secondary,#52514e)}" +
    "#accessGate input{width:100%;box-sizing:border-box;padding:11px 12px;font-size:15px;border-radius:10px;" +
    "border:1px solid var(--border,rgba(11,11,11,.1));background:var(--surface-2,#fff);color:var(--text-primary,#0b0b0b);font-family:inherit}" +
    "#accessGate input:focus{outline:2px solid color-mix(in srgb,var(--series-1,#2a78d6) 45%,transparent);outline-offset:-1px;border-color:var(--series-1,#2a78d6)}" +
    "#accessGate button{width:100%;margin-top:12px;padding:11px 14px;font-size:14px;font-weight:700;border-radius:10px;cursor:pointer;" +
    "border:1px solid var(--series-1,#2a78d6);background:var(--series-1,#2a78d6);color:#fff;font-family:inherit}" +
    "#accessGate button:disabled{opacity:.6;cursor:default}" +
    "#accessGate .ag-msg{min-height:18px;margin-top:10px;font-size:12.5px;color:var(--up,#d03b3b)}" +
    "#accessGate .ag-note{margin-top:8px;font-size:11px;color:var(--muted,#898781)}";
  (document.head || root).appendChild(style);

  /* ---------------- SHA-256 ---------------- */
  function hex(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return s;
  }

  // crypto.subtle 은 보안 컨텍스트(https / localhost)에서만 제공되므로, 그 외(http://LAN-IP 등)를 위한 순수 JS 구현.
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  function sha256Bytes(msg) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var l = msg.length, bitHi = Math.floor((l * 8) / 0x100000000), bitLo = (l * 8) >>> 0;
    var padLen = (((l + 9 + 63) >> 6) << 6);
    var m = new Uint8Array(padLen);
    m.set(msg); m[l] = 0x80;
    m[padLen - 8] = bitHi >>> 24; m[padLen - 7] = bitHi >>> 16; m[padLen - 6] = bitHi >>> 8; m[padLen - 5] = bitHi;
    m[padLen - 4] = bitLo >>> 24; m[padLen - 3] = bitLo >>> 16; m[padLen - 2] = bitLo >>> 8; m[padLen - 1] = bitLo;
    var w = new Array(64);
    function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
    for (var off = 0; off < padLen; off += 64) {
      for (var i = 0; i < 16; i++) {
        var j = off + i * 4;
        w[i] = ((m[j] << 24) | (m[j + 1] << 16) | (m[j + 2] << 8) | m[j + 3]) >>> 0;
      }
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var out = new Uint8Array(32);
    for (i = 0; i < 8; i++) {
      out[i * 4] = H[i] >>> 24; out[i * 4 + 1] = H[i] >>> 16; out[i * 4 + 2] = H[i] >>> 8; out[i * 4 + 3] = H[i];
    }
    return out;
  }

  function sha256Hex(text) {
    var bytes = new TextEncoder().encode(text);
    if (window.crypto && crypto.subtle && crypto.subtle.digest) {
      return crypto.subtle.digest("SHA-256", bytes).then(function (buf) { return hex(new Uint8Array(buf)); });
    }
    return Promise.resolve(hex(sha256Bytes(bytes)));
  }

  function sameHex(a, b) {   // 길이가 같을 때 끝까지 비교(조기 종료 없음)
    a = String(a).toLowerCase(); b = String(b).toLowerCase();
    if (a.length !== b.length) return false;
    var diff = 0;
    for (var i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
  }

  /* ---------------- 설정 / 상태 ---------------- */
  function loadConfig() {
    return fetch(CONFIG_URL, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (c) {
      // digest 는 문자열 1개 또는 문자열 배열(접속 코드를 여러 개 허용). 하나라도 형식이 틀리면 fail-closed.
      var list = (c && c.digest != null) ? [].concat(c.digest) : [];
      var valid = list.length > 0 && list.every(function (d) { return /^[0-9a-f]{64}$/i.test(String(d)); });
      if (!valid) throw new Error("access.json 형식 오류 (digest)");
      c.digests = list.map(function (d) { return String(d).toLowerCase(); });
      cfg = c;
      return c;
    });
  }
  function readToken() {
    try { return JSON.parse(sessionStorage.getItem(SS_KEY) || "null"); } catch (_) { return null; }
  }
  function tokenValid(c) {
    var t = readToken();
    // version 이 같고, 세션을 연 코드의 digest 가 아직 허용 목록에 있어야 유효
    // → 코드를 바꾸거나 폐기하면 그 코드로 들어온 기존 세션이 즉시 무효화된다.
    return !!t && t.v === c.version && c.digests.some(function (d) { return sameHex(t.d || "", d); });
  }
  function grant() {
    root.classList.remove("access-locked");
    var gate = document.getElementById("accessGate");
    if (gate) gate.remove();
    var fns = waiters; waiters = [];
    fns.forEach(function (fn) { fn(); });
  }

  /* ---------------- 공개 API ---------------- */
  /** 입력한 코드를 SHA-256 으로 해시해 access.json 의 digest 와 비교한다. 일치하면 접근 허용 상태를 기록하고 true. */
  function unlock(code) {
    var input = String(code == null ? "" : code).trim().normalize("NFC");
    if (!input) return Promise.resolve(false);
    var ready = cfg ? Promise.resolve(cfg) : loadConfig();
    return ready.then(function (c) {
      return sha256Hex(input).then(function (h) {
        var matched = null;   // 목록 전체를 끝까지 비교한다(일치 위치에 따른 조기 종료 없음)
        c.digests.forEach(function (d) { if (sameHex(h, d)) matched = d; });
        if (!matched) return false;
        try {
          sessionStorage.setItem(SS_KEY, JSON.stringify({ v: c.version, d: matched }));
          sessionStorage.removeItem(SS_FAIL); sessionStorage.removeItem(SS_UNTIL);
        } catch (_) {}
        grant();
        return true;
      });
    });
  }

  /** 접근 허용 상태를 지우고 게이트를 다시 표시한다. */
  function lockSite() {
    try { sessionStorage.removeItem(SS_KEY); } catch (_) {}
    location.reload();
  }

  function renderGate(loadError) {
    if (document.getElementById("accessGate")) return;
    var gate = document.createElement("div");
    gate.id = "accessGate";
    gate.setAttribute("role", "dialog"); gate.setAttribute("aria-modal", "true"); gate.setAttribute("aria-labelledby", "accessTitle");
    gate.innerHTML =
      '<form id="accessForm" autocomplete="off" novalidate>' +
      '<div class="ag-brand"><span class="ag-dot"></span><h1 id="accessTitle">Stock Alert</h1></div>' +
      '<p>초대받은 사용자를 위한 정보 공간입니다.<br>접속 코드를 입력해 주세요.</p>' +
      '<input id="accessCode" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" ' +
      'placeholder="접속 코드" aria-label="접속 코드">' +
      '<button type="submit" id="accessBtn">입장</button>' +
      '<div class="ag-msg" id="accessMsg" role="alert" aria-live="polite"></div>' +
      '<div class="ag-note">간단한 접근 제한이며 보안 경계가 아닙니다.</div>' +
      '</form>';
    document.body.appendChild(gate);

    var form = gate.querySelector("#accessForm"), inp = gate.querySelector("#accessCode"),
        btn = gate.querySelector("#accessBtn"), msg = gate.querySelector("#accessMsg");
    if (loadError) {
      msg.textContent = "접속 설정을 불러오지 못했습니다. 잠시 후 새로고침 해주세요.";
      inp.disabled = true; btn.textContent = "새로고침";
      form.addEventListener("submit", function (e) { e.preventDefault(); location.reload(); });
      return;
    }
    inp.focus();
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var until = +sessionStorage.getItem(SS_UNTIL) || 0;
      if (Date.now() < until) {
        msg.textContent = "시도가 너무 많습니다. " + Math.ceil((until - Date.now()) / 1000) + "초 후에 다시 시도해 주세요.";
        return;
      }
      btn.disabled = true; msg.textContent = "";
      unlock(inp.value).then(function (ok) {
        if (ok) return;   // grant() 가 게이트를 제거함
        var n = (+sessionStorage.getItem(SS_FAIL) || 0) + 1;
        try {
          sessionStorage.setItem(SS_FAIL, String(n));
          if (n >= MAX_FREE_TRIES) {
            var wait = Math.min(60, Math.pow(2, n - MAX_FREE_TRIES + 1));
            sessionStorage.setItem(SS_UNTIL, String(Date.now() + wait * 1000));
          }
        } catch (_) {}
        msg.textContent = "접속 코드가 올바르지 않습니다.";
        inp.value = ""; inp.focus();
      }).catch(function () {
        msg.textContent = "확인 중 오류가 발생했습니다. 새로고침 후 다시 시도해 주세요.";
      }).then(function () { btn.disabled = false; });
    });
  }

  /** 게이트를 초기화한다. 접근이 허용되면(이미 허용된 세션 포함) resolve 되는 Promise 를 반환한다. */
  function initAuth() {
    if (initPromise) return initPromise;
    initPromise = new Promise(function (resolve) {
      waiters.push(resolve);
      var start = function () {
        loadConfig().then(function (c) {
          if (tokenValid(c)) grant(); else renderGate(false);
        }).catch(function (err) {
          console.error("[access] 설정 로드 실패:", err);
          renderGate(true);      // fail-closed
        });
      };
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
      else start();
    });
    return initPromise;
  }

  window.initAuth = initAuth;
  window.unlock = unlock;
  window.lockSite = lockSite;
  window.SiteAuth = { initAuth: initAuth, unlock: unlock, lockSite: lockSite, sha256Hex: sha256Hex, sha256Pure: function (t) { return hex(sha256Bytes(new TextEncoder().encode(t))); } };
})();
