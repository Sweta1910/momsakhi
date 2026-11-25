"""Headless check: in-app browsers (Instagram) see the open-in-browser card up front, carrying #q/<id>.

Serves the repo with http.server, stubs backend.js (no Firebase, no real accounts).
Run: python tests/iab_upfront_playwright.py   (exit 1 on failure)
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



UAS = {
    "instagram-android": "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 Mobile Safari/537.36 Instagram 330.0.0.38.89 Android (34/14; 420dpi; 1080x2400; Google; Pixel 7; panther; tensor; en_US; 600000000)",
    "instagram-iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21E219 Instagram 330.0.1.19.99 (iPhone14,5; iOS 17_4; en_US; en; scale=3.00; 1170x2532; 600000000)",
    "chrome-android": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
}


def load(browser, base, ua):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block", user_agent=ua)
    ctx.route("**/backend.js*", lambda r: r.fulfill(body=STUB, content_type="text/javascript"))
    page = ctx.new_page()
    page.goto(base + "/#q/" + QID)
    page.wait_for_selector("#google-signin")
    page.wait_for_timeout(300)
    return ctx, page


def check(name, cond, detail=""):
    print("  %s: %s %s" % (name, "ok" if cond else "FAIL", detail))
    return bool(cond)


def main():
    srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    ok = True
    shot = os.environ.get("IAB_SHOT")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in ("instagram-android", "instagram-iphone", "chrome-android"):
            print(name)
            ctx, page = load(browser, base, UAS[name])
            card = page.locator("#iab-card")
            if name == "chrome-android":
                ok &= check("no card", card.count() == 0)
            else:
                vis = card.count() == 1 and card.is_visible()
                ok &= check("card visible without tapping sign-in", vis)
                link = page.locator("#iab-link").input_value() if card.count() else ""
                ok &= check("link ends with #q/id", link.endswith("#q/" + QID), link)
                ok &= check("google button still there", page.locator("#google-signin").count() == 1)
                if name == "instagram-android":
                    href = page.get_attribute("#iab-chrome", "href") if card.count() else ""
                    ok &= check("intent has thread", "#q/" + QID in (href or ""), href)
                if name == "instagram-iphone" and shot:
                    page.screenshot(path=shot)
            ctx.close()
        browser.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


main()
