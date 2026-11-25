"""Headless check: an invited mom lands on her #q/<id> thread after sign-in.

Serves the repo with http.server, replaces backend.js with an in-memory stub
(no Firebase, no network, no real accounts), then drives the real app.js:
  1. NEW mom: signed out at #q/<id> -> Continue with Google -> city -> about ->
     Enter -> location.hash must be #q/<id>.
  2. EXISTING member (profile already saved): same start -> hash is #q/<id>.
Run: python tests/invite_return_playwright.py   (exit 1 on failure)
"""
import http.server
import os
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QID = "1Map2fSrjAtGLh4YAz9A"

STUB = """
(function () {
  var cbs = [], profiles = {};
  var F = function () { var f = function () {}; f.then = function (r) { return Promise.resolve(null).then(r); };
    f.catch = function () { return f; }; return f; };
  var B = { isReal: true, user: null, posts: [], usingEmulators: false };
  B.ready = Promise.resolve();
  B.onAuth = function (cb) { cbs.push(cb); setTimeout(function () { cb(B.user); }, 0); return function () {}; };
  B.getRedirectResult = function () { return Promise.resolve(null); };
  B.signInWithGoogle = function () {
    var u = { uid: "stub-uid", displayName: "Test Mom", email: "test@example.invalid" };
    return new Promise(function (res) { setTimeout(function () { B.user = u; cbs.forEach(function (c) { c(u); }); res({ user: u }); }, 20); });
  };
  B.getProfile = function (uid) { return Promise.resolve(profiles[uid] || (window.__seedProfile ? { nickname: "Test", city: "Pune" } : null)); };
  B.saveProfile = function (uid, doc) { profiles[uid] = doc; return Promise.resolve(); };
  B.getPost = function () { return Promise.resolve(null); };
  B.checkModerator = function () { return Promise.resolve(false); };
  window.Backend = new Proxy(B, { get: function (t, k) { return k in t ? t[k] : (typeof k === "string" ? F() : undefined); },
    set: function (t, k, v) { t[k] = v; return true; } });
})();
"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass


def run_case(browser, base, existing):
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block")
    ctx.route("**/backend.js*", lambda r: r.fulfill(body=STUB, content_type="text/javascript"))
    if existing:
        ctx.add_init_script("window.__seedProfile = true;")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(base + "/#q/" + QID)
    page.wait_for_selector("#google-signin")
    note = page.locator("#welcome-return").count()
    page.click("#google-signin")
    if not existing:
        try:
            page.wait_for_selector("#city-input", timeout=5000)
        except Exception:
            print("DEBUG", page.evaluate("location.hash"), page.inner_text("#screen")[:300])
            raise
        page.fill("#city-input", "Pune")
        page.click("[data-act=city-continue]")
        page.wait_for_function("!document.querySelector('#about-continue').disabled", timeout=5000)
        page.click("#about-continue")
        page.wait_for_selector("#enter-app", timeout=5000)
        page.wait_for_function("!document.querySelector('#enter-app').disabled", timeout=5000)
        page.click("#enter-app")
    page.wait_for_timeout(600)
    h = page.evaluate("location.hash")
    ctx.close()
    return h, note, errs


def main():
    srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, existing in (("new mom", False), ("existing member", True)):
            try:
                h, note, errs = run_case(browser, base, existing)
            except Exception as e:  # noqa: BLE001
                h, note, errs = "ERROR " + str(e).splitlines()[0], 0, []
            good = h == "#q/" + QID
            ok = ok and good
            print("%s: final hash=%s, sign-in line shown=%s, page errors=%s -> %s"
                  % (name, h, bool(note), errs, "PASS" if good else "FAIL"))
        browser.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


main()
