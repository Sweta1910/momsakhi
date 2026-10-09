"""Structural tests for the MomSakhi web prototype (served from the repo root;
web/ only holds a redirect stub for old /web/#route links).

These are stdlib-only and fast: they prove the static app is complete and
self-consistent without a browser. Rendering and click-path coverage lives
in scripts/screenshots.py (Playwright), which fails on any uncaught page error.
"""

import html.parser
import json
import os
import re
import shutil
import subprocess
import unittest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# The app is served from the repo root (GitHub Pages root) since 2026-10-09.
WEB_DIR = APP_DIR
DATA_PREFIX = "window.AANGAN_DATA = "


def _read(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def load_data():
    """data.js is `window.AANGAN_DATA = <strict JSON>;` so it can be parsed here."""
    src = _read("data.js").strip()
    assert src.startswith(DATA_PREFIX), "data.js must start with the AANGAN_DATA prefix"
    return json.loads(src[len(DATA_PREFIX):].rstrip(";"))


class _Collector(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.scripts, self.styles, self.stack, self.errors = set(), [], [], [], []

    void = {"meta", "link", "br", "img", "input", "hr", "source"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids:
                self.errors.append("duplicate id " + a["id"])
            self.ids.add(a["id"])
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet" and not a["href"].startswith("http"):
            self.styles.append(a["href"])
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append("mismatched </%s>" % tag)
        else:
            self.stack.pop()


class TestShell(unittest.TestCase):
    def test_index_parses_and_references_exist(self):
        p = _Collector()
        p.feed(_read("index.html"))
        self.assertEqual(p.errors, [])
        self.assertEqual(p.stack, [], "unclosed tags in index.html")
        for needed in ("screen", "tabbar", "sheet", "toast", "dt-logo", "right-rail"):
            self.assertNotIn("showcase", p.ids)
            self.assertNotIn("phone", p.ids)
            self.assertIn(needed, p.ids)
        self.assertEqual([s.split("?")[0] for s in p.scripts], ["data.js", "firebase-config.js", "backend.js", "app.js"], "scripts must load in correct order")
        for ref in p.scripts + p.styles:
            self.assertTrue(os.path.exists(os.path.join(WEB_DIR, ref.split("?")[0])), ref)

    def test_viewport_and_description_meta(self):
        src = _read("index.html")
        self.assertIn('name="viewport"', src)
        self.assertIn('name="description"', src)

    def test_cache_busting_present(self):
        html = _read("index.html")
        self.assertRegex(html, r'src="app\.js\?v=[\da-f]{7}"')
        self.assertRegex(html, r'src="backend\.js\?v=[\da-f]{7}"')
        # styles.css is versioned too (layout fixes must not hide behind a cached CSS),
        # and every asset carries the SAME version so one bump refreshes everything.
        self.assertRegex(html, r'href="styles\.css\?v=[\da-f]{7}"')
        self.assertEqual(len(set(re.findall(r'\?v=([\da-f]{7})"', html))), 1)

    def test_js_syntax_with_node_if_available(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        for name in ("data.js", "app.js"):
            r = subprocess.run([node, "--check", os.path.join(WEB_DIR, name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_css_braces_balanced(self):
        css = re.sub(r"/\*.*?\*/", "", _read("styles.css"), flags=re.S)
        self.assertEqual(css.count("{"), css.count("}"))


class TestData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load_data()

    def test_brand_is_single_constant(self):
        self.assertEqual(self.d["brand"]["name"], "MomSakhi")
        self.assertEqual(self.d["brand"]["tagline"], "A sakhi for every stage of motherhood.")
        # app.js must read the name from data, never hard-code it.
        self.assertNotIn('"MomSakhi"', _read("app.js"))
        self.assertNotIn('"Aangan"', _read("app.js"))

    def test_city_suggestions_are_global_and_free_text(self):
        # City is optional free text; data.js only offers datalist suggestions.
        # 2026-10-09: audience is Indian moms ANYWHERE (India + diaspora), so the
        # list mixes Indian metros with diaspora hubs written "City, Country".
        self.assertNotIn("cities", self.d)
        sugg = self.d["citySuggestions"]
        self.assertTrue({"Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune",
                         "Ahmedabad", "Jaipur", "Lucknow", "Chandigarh", "Kochi", "Indore",
                         "Bhubaneswar", "Noida", "Gurugram"} <= set(sugg))
        self.assertTrue({"Bay Area, USA", "San Jose, USA", "Seattle, USA", "Dallas, USA", "Houston, USA",
                         "Chicago, USA", "Edison, NJ, USA", "New York, USA", "Atlanta, USA",
                         "Toronto, Canada", "Vancouver, Canada", "London, UK", "Leicester, UK",
                         "Birmingham, UK", "Dubai, UAE", "Abu Dhabi, UAE", "Singapore",
                         "Sydney, Australia", "Melbourne, Australia", "Auckland, New Zealand"} <= set(sugg))
        self.assertTrue(45 <= len(sugg) <= 60, len(sugg))
        self.assertEqual(len(sugg), len(set(sugg)))
        self.assertTrue(all(0 < len(c) <= 40 for c in sugg))
        # Every non-India entry names its country (Singapore is a city-state).
        abroad = sugg[sugg.index("Bay Area, USA"):]
        self.assertTrue(all(", " in c or c == "Singapore" for c in abroad), abroad)
        self.assertFalse({"Mountain View", "Sunnyvale", "Cupertino"} & set(sugg))

    def test_required_languages_and_stages(self):
        self.assertEqual(set(self.d["languages"]), {"English", "Hindi", "Tamil", "Telugu", "Kannada", "Marathi",
                                                     "Bengali", "Gujarati", "Punjabi", "Malayalam"})
        self.assertEqual(len(self.d["stages"]), 4)

    def test_reactions_are_supportive_only(self):
        labels = {r["label"].lower() for r in self.d["reactions"]}
        self.assertEqual(labels, {"hug", "been there", "helpful"})
        self.assertFalse(any("down" in l or "dislike" in l for l in labels))

    def test_posts_reference_known_circles_and_have_anon_examples(self):
        circles = {c["id"] for c in self.d["circles"]}
        self.assertGreaterEqual(len(circles), 9)
        for p in self.d["posts"]:
            self.assertIn(p["circle"], circles, p["id"])
            self.assertEqual(p["anon"], p["author"] is None, p["id"])
        self.assertTrue(any(p["anon"] for p in self.d["posts"]))
        self.assertTrue(any(not p["anon"] for p in self.d["posts"]))

    def test_expert_badge_example_exists(self):
        experts = [a for p in self.d["posts"] for a in p["answers"] if a.get("expert")]
        self.assertTrue(experts)
        self.assertIn("Lactation", experts[0]["expert"]["role"])

    def test_nearby_is_neighbourhood_level_only(self):
        hoods = {h["id"]: h for h in self.d["neighbourhoods"]}
        for m in self.d["moms"]:
            self.assertIn(m["area"], hoods)
            self.assertTrue(m["distance"].startswith("~"), "distances must be approximate")
            for banned in ("lat", "lng", "lon", "address", "street"):
                self.assertNotIn(banned, m)

    def test_ids_unique(self):
        for key in ("circles", "posts", "moms", "events", "neighbourhoods"):
            ids = [x["id"] for x in self.d[key]]
            self.assertEqual(len(ids), len(set(ids)), key)

    def test_chats_only_for_mutually_accepted_moms(self):
        moms = {m["id"]: m for m in self.d["moms"]}
        for mid in self.d["chats"]:
            self.assertEqual(moms[mid]["status"], "accepted")

    def test_kindness_demo_triggers_and_rewrites(self):
        k = self.d["kindness"]
        phrases = [p["match"] for p in k["phrases"]]
        for demo in (k["demo"], k["demoAsk"]):
            self.assertTrue(any(re.search(r"\b" + re.escape(p) + r"\b", demo.lower()) for p in phrases), demo)
            rewrite = [r["to"] for r in k["rewrites"] if r["from"] == demo]
            self.assertEqual(len(rewrite), 1)
            self.assertFalse(any(re.search(r"\b" + re.escape(p) + r"\b", rewrite[0].lower()) for p in phrases))


    def test_safety_centre(self):
        app_js = _read("app.js")
        self.assertIn("1-833-852-6262", app_js)
        self.assertIn("988", app_js)
        self.assertIn("1-800-944-4773", app_js)
        # 2026-10-09 re-verification: PSI Spanish text line, 988 chat, hotline languages.
        self.assertIn("sms:19712037773", app_js)
        self.assertIn("https://chat.988lifeline.org/", app_js)
        self.assertIn("1-833-TLC-MAMA", app_js)
        self.assertIn("WORRY_PHRASES", app_js)

    def test_no_soon_stub_for_safety(self):
        app_js = _read("app.js")
        self.assertNotIn('data-act="soon">' + 'icon("shield") + \'<span class="grow">Safety centre & crisis lines</span>', app_js)

    def test_postpartum_circle_exists(self):
        circles = {c["id"] for c in self.d["circles"]}
        self.assertIn("postpartum-feelings", circles)

    def test_views_exist_for_every_screen(self):
        js = _read("app.js")
        for view in ("V.welcome", 'V["onboard/city"]', 'V["onboard/about"]', 'V["onboard/verify"]', "V.home",
                     "V.ask", "V.q", "V.nearby", "V.meetups", "V.chat", "V.me", "V.safety"):
            self.assertIn(view + " = function", js)

    def test_google_and_phone_auth_elements(self):
        app_js = _read("app.js")
        styles = _read("styles.css")
        # Google sign-in button exists with official branding
        self.assertIn("Continue with Google", app_js)
        self.assertIn("btn-google", app_js)
        self.assertIn(".btn-google", styles)
        self.assertIn("google-signin", app_js)

        # "or" divider exists between sign-in options
        self.assertIn("auth-divider", app_js)
        self.assertIn(".auth-divider", styles)
        self.assertIn(">or<", app_js)

        # signInWithGoogle demo stub exists with Firebase Auth migration documentation
        self.assertIn("function signInWithGoogle", app_js)
        self.assertIn("GoogleAuthProvider", app_js)
        self.assertIn("signInWithPopup", app_js)

        # Phone flow is still present
        self.assertIn("verify-phone", app_js)
        self.assertIn("Phone verified", app_js)
        self.assertIn("get-started", app_js)

    def test_no_selfie_references_in_web(self):
        for root, dirs, files in os.walk(WEB_DIR):
            # Only shipped app files: skip git internals, scratch and node deps.
            dirs[:] = [d for d in dirs if d not in (".git", "tmp", "node_modules", "screenshots")]
            for fname in files:
                if fname.endswith((".js", ".html", ".css", ".json")):
                    path = os.path.join(root, fname)
                    with open(path, encoding="utf-8") as f:
                        content = f.read().lower()
                        self.assertNotIn("selfie", content, f"Found unexpected 'selfie' reference in {fname}")

    def test_no_saathi_references_in_codebase(self):
        root_dir = APP_DIR
        for root, dirs, files in os.walk(root_dir):
            if ".git" in root.split(os.sep):
                continue
            for fname in files:
                path = os.path.join(root, fname)
                if fname == "test_aangan_web.py":
                    continue
                if fname.endswith((".js", ".html", ".css", ".json", ".md", ".py")):
                    try:
                        with open(path, encoding="utf-8") as f:
                            content = f.read().lower()
                            self.assertNotIn("saathi", content, f"Found unexpected 'saathi' reference in {path}")
                    except Exception:
                        pass


    def test_css_has_responsive_layout(self):
        css = _read("styles.css")
        self.assertNotIn('.phone {', css)
        self.assertNotIn('.showcase {', css)
        self.assertIn('@media (min-width: 900px)', css, "Must have desktop breakpoint")
        self.assertIn('.app.onboarding-mode', css, "Must have desktop overrides for onboarding mode")
        self.assertIn('.app.onboarding-mode .welcome {', css, "Must style desktop welcome container")
        self.assertIn('@media (min-width: 1200px)', css, "Must have right-rail breakpoint")


    def test_firebase_config_is_wellformed(self):
        # The real web config is committed on purpose: Firebase web apiKeys are
        # public by design; access is controlled by firestore.rules + authorized domains.
        js = _read("firebase-config.js")
        self.assertIn('window.FIREBASE_CONFIG', js)
        self.assertNotIn('PASTE_', js, "placeholders must be replaced by the real config")
        for key in ("apiKey", "authDomain", "projectId", "appId"):
            self.assertRegex(js, r'\b%s:\s*"[^"]+"' % key)
        self.assertIn('aangan-6a58c.firebaseapp.com', js)

    def test_backend_demo_mode_guard(self):
        js = _read("backend.js")
        self.assertIn('window.FIREBASE_CONFIG.apiKey', js)
        self.assertIn('PASTE', js)
        self.assertIn('isReal = false', js)

    def test_emulator_hook_only_on_localhost_with_flag(self):
        # The emulator hook must be impossible to trigger on the live site.
        js = _read("backend.js")
        self.assertIn("if (useEmulators(window.location))", js)
        node = shutil.which("node") or os.path.expanduser("~/.local/bin/node")
        if not os.path.exists(node):
            self.skipTest("node not available")
        harness = (
            "global.window=global;" + js +
            ";var f=window.Backend._useEmulators;var cases=["
            "[{hostname:'localhost',search:'?emu=1'},true],"
            "[{hostname:'127.0.0.1',search:'?a=b&emu=1'},true],"
            "[{hostname:'localhost',search:''},false],"
            "[{hostname:'localhost',search:'?emu=10'},false],"
            "[{hostname:'sweta1910.github.io',search:'?emu=1'},false],"
            "[{hostname:'localhost.evil.com',search:'?emu=1'},false],"
            "[null,false]];"
            "cases.forEach(function(c){if(f(c[0])!==c[1]){console.log('FAIL '+JSON.stringify(c));process.exit(1);}});"
            "console.log('ok');")
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_onboarding_layout_only_on_onboarding_routes(self):
        # Post/chat pages (tab: null) must not get the centred welcome layout,
        # which squashed a post + replies into one row on laptops.
        js = _read("app.js")
        self.assertIn('var isOnboarding = r.name === "welcome" || r.name.indexOf("onboard/") === 0;', js)
        self.assertIn('app.classList.toggle("onboarding-mode", isOnboarding)', js)
        self.assertNotIn('app.classList.toggle("onboarding-mode", isPreAuth)', js)

    def test_top_nav_kept_on_post_and_chat_pages_on_laptop(self):
        # Laptop: post/chat pages keep the top menu (plus the ← backbar); phones hide
        # the bar there via .detail-nav. Onboarding still hides it outright.
        js, css = _read("app.js"), _read("styles.css")
        self.assertIn('var isDetail = !isOnboarding && out.tab === null && r.name !== "chats";', js)
        # Only extra hidden case: #privacy read from the welcome screen before joining.
        self.assertIn('tabbar.hidden = isOnboarding || (r.name === "privacy" && !store.onboarded);', js)
        self.assertIn('tabbar.classList.toggle("detail-nav", isDetail);', js)
        self.assertNotIn('tabbar.hidden = isPreAuth', js)
        self.assertIn('data-act="back" aria-label="Back"', js)
        mobile = css.index(".tabbar.detail-nav { display: none; }")
        desktop = css.index(".tabbar.detail-nav:not([hidden]) { display: flex; }")
        self.assertLess(mobile, css.index("@media (min-width: 900px)"))
        self.assertGreater(desktop, css.index("@media (min-width: 900px)"))

    def test_firestore_rules(self):
        with open(os.path.join(APP_DIR, "firestore.rules")) as f:
            rules = f.read()
        self.assertIn("allow read, write: if false;", rules)
        self.assertIn("request.auth.uid == uid", rules)
        self.assertIn("resource.data.uid == request.auth.uid", rules)

    def test_anon_posts_no_author_name(self):
        js = _read("app.js")
        self.assertIn('var authorName = isAnon ? null : store.profile.nickname;', js)


class TestRealModeHardening(unittest.TestCase):
    """Real (Firebase) mode used to fail silently: un-caught promises, undefined
    Firestore fields, a premature "Demo mode" badge. These pin the fixes."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def _calls(self, name):
        return [m.start() for m in re.finditer(r"Backend\.%s\(" % name, self.app)]

    def test_every_backend_write_and_profile_read_is_caught(self):
        for name in ("addPost", "addReply", "addReport", "saveProfile", "getProfile", "signOut", "getRedirectResult",
                     "removePost", "deleteReport", "getPost"):
            calls = self._calls(name)
            self.assertTrue(calls, "app.js never calls Backend.%s" % name)
            for start in calls:
                # The promise chain for each call must end in a .catch within the
                # same statement block (before the next `break;` or 1500 chars).
                window = self.app[start:start + 1500]
                end = window.find("break;")
                if end > 0:
                    window = window[:end]
                self.assertIn(".catch(", window, "Backend.%s call at %d has no .catch" % (name, start))

    def test_fail_toast_shows_code_and_logs(self):
        self.assertIn("function failToast(", self.app)
        self.assertIn("console.error(", self.app)
        self.assertIn("Please try again.", self.app)
        self.assertIn("function busy(", self.app)

    def test_demo_label_only_after_ready(self):
        boot = self.app[self.app.index('document.addEventListener("DOMContentLoaded"'):]
        ready = boot.index("Backend.ready.then(")
        first_label = boot.index("showDemoLabel()")
        self.assertGreater(first_label, ready, "Demo label must wait for Backend.ready")
        self.assertNotIn('d.innerHTML = "Demo mode"', boot, "label must come from showDemoLabel, not inline at load")

    def test_posting_requires_sign_in_in_real_mode(self):
        self.assertIn("Please sign in to post", self.app)
        self.assertIn("var isAnon = !!askDraft.anon;", self.app)
        self.assertIn("store.profile.stages || []", self.app)

    def test_addpost_never_writes_undefined(self):
        self.assertIn("!!isAnon", self.backend)
        self.assertIn("function plain(", self.backend)
        for field in ("title: str(title", "body: str(body", "meta: str(meta", "hue: str(hue"):
            self.assertIn(field, self.backend)

    def test_redirect_sign_in_fallback(self):
        for code in ("auth/popup-blocked", "auth/operation-not-supported-in-this-environment",
                     "auth/cancelled-popup-request"):
            self.assertIn(code, self.backend)
        self.assertIn("signInWithRedirect(auth, provider)", self.backend)
        self.assertIn("fbGetRedirectResult(auth)", self.backend)
        self.assertIn("Backend.getRedirectResult()", self.app)

    def test_reply_count_increment_allowed_by_rules(self):
        self.assertIn("replyCount: increment(1)", self.backend)
        self.assertIn("allow update:", self.rules)
        self.assertIn("affectedKeys().hasOnly(['replyCount'])", self.rules)
        self.assertIn("p.replyCount || 0", self.app)
        self.assertIn("match /replies/{replyId}", self.rules)

    def test_null_created_at_and_missing_fields_render(self):
        self.assertIn('if (!t) return "just now";', self.app)
        self.assertIn('serverTimestamps: "estimate"', self.backend)
        self.assertIn("reactionBar(p.id, p.reactions || {})", self.app)
        self.assertIn("p.circle ? circle(p.circle) : null", self.app)

    def test_listeners_have_error_callbacks_and_wait_for_sign_in(self):
        # posts, replies, reports: every listener has an error callback.
        self.assertEqual(self.backend.count("onSnapshot(q, function(snap)"), 4)  # + feedback (moderators)
        self.assertEqual(self.backend.count("if (onError) onError(e);"), 5)  # posts, replies, reports, my reactions, feedback (mods)
        self.assertIn("if (!B.user) { B.posts = []; return; }", self.app)

    def test_posts_and_replies_listeners_self_heal_without_polling(self):
        # A dead onSnapshot listener used to freeze the feed until reload.
        self.assertIn('healListener("posts", "load posts")', self.app)
        self.assertIn('healListener("replies", "load replies")', self.app)
        self.assertNotIn('failToast("load posts", null));', self.app)
        self.assertIn("Math.min(60000, 2000 * Math.pow(2, live.retry++))", self.app)
        self.assertIn('window.addEventListener("online", reviveListeners);', self.app)
        self.assertIn("if (!document.hidden) reviveListeners();", self.app)
        self.assertNotIn("setInterval(", self.app)  # no polling
        # one listener per view: the old one is always torn down before re-attaching
        self.assertIn("if (B._unsubPosts) { B._unsubPosts(); B._unsubPosts = null; }", self.app)
        self.assertIn("if (B._unsubReplies) { B._unsubReplies(); B._unsubReplies = null; }", self.app)

    def test_circle_optional_when_posting(self):
        # canPost check only needs title > 4 chars, circle is optional
        self.assertIn("var canPost = askDraft.title.trim().length > 4;", self.app)
        self.assertNotIn("askDraft.circle && askDraft.title", self.app)
        # circle picker label indicates optional
        self.assertIn('Circle <span class="tiny">(optional)</span>', self.app)
        # ask-post button has hint when disabled
        self.assertIn('id="ask-hint"', self.app)
        self.assertIn("Add a title (at least 5 characters) to post", self.app)
        # circle can be deselected by clicking again
        self.assertIn("askDraft.circle = (askDraft.circle === id ? null : id);", self.app)
        # firestore rules do not mandate circle field
        self.assertNotIn("request.resource.data.circle is string", self.rules)
        # backend stores null when circle is empty/not chosen
        self.assertIn('circle: (circle && typeof circle === "string" && circle.trim()) ? circle.trim() : null', self.backend)

    def test_backend_js_syntax_with_node_if_available(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        r = subprocess.run([node, "--check", os.path.join(WEB_DIR, "backend.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_real_mode_vs_demo_mode_wording(self):
        # In real mode, copy is warm and honest: no claims that data is fictional.
        # Demo mode retains the prototype/fictional notices.
        # 1. Welcome screen
        self.assertIn('"Real moms, real posts · sign in with Google to join"', self.app)
        self.assertIn('"Prototype · all people, posts and places are fictional demo data"', self.app)
        self.assertIn('(isRealMode() ? "Real moms, real posts · sign in with Google to join" : "Prototype · all people, posts and places are fictional demo data")', self.app)

        # 2. Me tab footer note
        self.assertIn('esc(BRAND.name) + (isRealMode() ? " · v0.1 · beta" : " prototype · v0.1 · all data is fictional")', self.app)

        # 3. Showcase footer note
        self.assertIn('(isRealMode() ? esc(BRAND.name) + " · v0.1 · beta" : "Clickable prototype · mock data only · all people are fictional")', self.app)

        # 4. Onboard verify demo notice
        self.assertIn('(isRealMode() ? "" : \'<p class="tiny" style="text-align:center;margin-top:10px">Demo: no real data is sent anywhere.</p>\')', self.app)

        # 5. Dynamic execution test verifying rendered HTML across both modes
        node = shutil.which("node") or os.path.expanduser("~/.local/bin/node")
        if not node:
            self.skipTest("node not installed")
        harness = """
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function runMode(isReal) {
  const fakeWindow = {
    location: { hash: '#welcome', search: '', hostname: 'localhost' },
    localStorage: {
      store: {},
      getItem: function(k) { return this.store[k] || null; },
      setItem: function(k, v) { this.store[k] = v; },
      removeItem: function(k) { delete this.store[k]; }
    },
    document: {
      addEventListener: () => {},
      querySelector: () => null,
      getElementById: () => null,
      body: { setAttribute: () => {} }
    },
    Backend: { isReal: isReal }
  };
  fakeWindow.window = fakeWindow;
  const ctx = vm.createContext(fakeWindow);
  vm.runInContext(dataJs, ctx);
  vm.runInContext(appJs, ctx);
  const V = fakeWindow.AANGAN.V;
  const welcome = V.welcome().html;
  const me = V.me().html;
  const verify = V['onboard/verify']().html;
  if (!welcome.includes('MomSakhi') || !welcome.includes('<em>sakhi</em> for every stage of motherhood.')) {
    throw new Error('Welcome missing MomSakhi name/tagline: ' + welcome);
  }
  if (/Aangan/.test(welcome + me + verify)) {
    throw new Error('Rendered screen still says Aangan');
  }
  if (isReal) {
    if (welcome.includes('fictional') || welcome.includes('demo data') || welcome.includes('Prototype')) {
      throw new Error('Real mode welcome contains fictional/demo text: ' + welcome);
    }
    if (!welcome.includes('Real moms, real posts · sign in with Google to join')) {
      throw new Error('Real mode welcome missing real-moms text: ' + welcome);
    }
    if (me.includes('fictional') || me.includes('all data is fictional')) {
      throw new Error('Real mode Me tab contains fictional text: ' + me);
    }
    if (!me.includes('· v0.1 · beta')) {
      throw new Error('Real mode Me tab missing beta text: ' + me);
    }
    if (verify.includes('Demo: no real data is sent anywhere.')) {
      throw new Error('Real mode verify contains demo notice: ' + verify);
    }
  } else {
    if (!welcome.includes('Prototype · all people, posts and places are fictional demo data')) {
      throw new Error('Demo mode welcome missing prototype text: ' + welcome);
    }
    if (!me.includes('prototype · v0.1 · all data is fictional')) {
      throw new Error('Demo mode Me tab missing prototype text: ' + me);
    }
    if (!verify.includes('Demo: no real data is sent anywhere.')) {
      throw new Error('Demo mode verify missing demo notice: ' + verify);
    }
  }
}
runMode(true);
runMode(false);
console.log('OK');
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestRebrandMomSakhi(unittest.TestCase):
    """The app was renamed Aangan -> MomSakhi. No user-visible "Aangan" may come back,
    but internal ids keep the old name on purpose (renaming them would log everyone
    out / orphan data): localStorage keys, the AANGAN_DATA global, the Firebase
    project id aangan-6a58c. Case-sensitive "Aangan" only ever meant the brand."""

    VISIBLE = ["index.html", "app.js", "data.js", "styles.css",
               "web/index.html", "README.md", "SETUP-FIREBASE.md"]

    def test_no_user_visible_aangan(self):
        root = APP_DIR
        for rel in self.VISIBLE:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                hits = [i + 1 for i, line in enumerate(f) if "Aangan" in line]
            self.assertEqual(hits, [], f"user-visible 'Aangan' left in {rel} at lines {hits}")

    def test_brand_shown_in_title_and_meta(self):
        html = _read("index.html")
        self.assertIn("<title>MomSakhi — A sakhi for every stage of motherhood.</title>", html)
        self.assertIn('<meta property="og:site_name" content="MomSakhi">', html)

    def test_internal_ids_kept(self):
        app = _read("app.js")
        self.assertIn('var STORE_KEY = "aangan.demo.v1";', app)
        self.assertIn("window.AANGAN_DATA", app)
        self.assertIn('projectId: "aangan-6a58c"', _read("firebase-config.js"))


class TestModeration(unittest.TestCase):
    """Moderation queue: moderators/{uid} made by hand in the console; rules gate it."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        cls.css = _read("styles.css")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def _block(self, header):
        i = self.rules.index(header)
        return self.rules[i:self.rules.index("\n    }", i)]

    def test_rules_is_moderator_helper(self):
        self.assertIn("function isModerator()", self.rules)
        self.assertIn("exists(/databases/$(database)/documents/moderators/$(request.auth.uid))", self.rules)

    def test_rules_no_client_can_write_moderators(self):
        block = self._block("match /moderators/{uid}")
        self.assertIn("allow write: if false;", block)
        self.assertIn("request.auth.uid == uid", block)  # may read only her own doc
        self.assertNotIn("create", block)
        self.assertNotIn("update", block)

    def test_rules_moderator_powers(self):
        reports = self._block("match /reports/{reportId}")
        self.assertIn("allow read, delete: if isModerator();", reports)
        self.assertIn("request.resource.data.reporterUid == request.auth.uid", reports)
        self.assertEqual(self.rules.count("(isModerator() || resource.data.uid == request.auth.uid)"), 2)

    def test_rules_keep_existing_and_deny_by_default(self):
        self.assertIn("match /{document=**} {\n      allow read, write: if false;", self.rules)
        self.assertIn("affectedKeys().hasOnly(['replyCount'])", self.rules)
        self.assertIn("request.resource.data.get('replyCount', 0) == 0", self.rules)
        self.assertIn("request.resource.data.get('author', null) == null", self.rules)
        self.assertNotIn("allow read: if false;", self._block("match /reports/{reportId}"))

    def test_backend_remove_post_cascades_in_one_batch(self):
        self.assertIn("Backend.removePost = function(postId)", self.backend)
        self.assertIn("writeBatch(db)", self.backend)
        self.assertIn('collection(db, "posts/" + postId + "/replies")', self.backend)
        self.assertIn('where("postId", "==", postId)', self.backend)
        self.assertIn("return batch.commit();", self.backend)
        self.assertIn('doc(db, "moderators", uid)', self.backend)
        self.assertIn('deleteDoc(doc(db, "reports", reportId))', self.backend)

    def test_app_moderation_screen(self):
        for s in ("V.mod = function", "Remove post", "Keep (dismiss report)", 'href="#mod"',
                  "window.confirm(", 'failToast("remove the post", el)', 'failToast("dismiss the report", el)',
                  'failToast("load reports", null)'):
            self.assertIn(s, self.app)
        self.assertIn("function canModerate() { return isRealMode() ? modState.isMod : true; }", self.app)

    def test_mod_flag_never_persisted(self):
        self.assertIn("var modState = {", self.app)
        self.assertNotIn("store.isMod", self.app)
        self.assertIn("syncModerator(u);", self.app)
        # checkModerator runs via the `B` alias; its chain must still end in .catch.
        i = self.app.index("B.checkModerator(u.uid)")
        self.assertIn(".catch(", self.app[i:i + 1200])
        self.assertIn("if (modState.unsub) { modState.unsub(); modState.unsub = null; }", self.app)

    def test_demo_mode_reports_in_local_store(self):
        self.assertIn("reports: [],        // demo-mode reports", self.app)
        self.assertIn("store.reports.unshift(", self.app)

    def test_account_id_with_copy(self):
        self.assertIn("Your account ID", self.app)
        self.assertIn('data-act="copy-uid"', self.app)
        self.assertIn("navigator.clipboard.writeText(myUid)", self.app)

    def test_moderation_css(self):
        for sel in (".btn-danger", ".mod-item", ".mod-actions", ".uid-row"):
            self.assertIn(sel, self.css)


def _node():
    for cand in (shutil.which("node"), os.path.expanduser("~/.local/bin/node"),
                 os.path.expanduser("~/liquid/state/scratch/jdk/node-v20.18.0-darwin-arm64/bin/node")):
        if cand and os.path.exists(cand):
            return cand
    return None


class TestOptionalCity(unittest.TestCase):
    """2026-10-09: city became OPTIONAL free text. Target users are Indian moms
    ANYWHERE in the world (India + diaspora: USA, UK, Canada, UAE, Singapore,
    Australia...), so any city worldwide is accepted.
    Only the meetup features -- the Meetups tab and Nearby moms -- need it and
    show an "Add your city" card until it is set. Feed/posting/circles never do.
    Real mode never shows the fictional demo meetups / moms / sample map."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.css = _read("styles.css")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def test_onboarding_city_is_optional_free_text(self):
        self.assertIn('data-act="city-skip"', self.app)
        self.assertIn("Skip for now", self.app)
        self.assertIn('list="city-suggestions"', self.app)
        self.assertIn("var CITY_MAX = 40;", self.app)
        self.assertIn('placeholder="e.g. Pune, San Jose, London"', self.app)
        self.assertNotIn("D.cities", self.app)
        self.assertNotIn('data-act="waitlist"', self.app)
        # Continue is never disabled on the city step.
        self.assertNotRegex(self.app, r'id="city-continue"[^>]*disabled')

    def test_city_hint_suggests_city_country_on_every_input(self):
        # Same-named cities (Hyderabad, Birmingham) must not merge meetups, so the
        # hint is part of cityField() itself -- not just the onboarding step.
        self.assertIn("var CITY_HINT = ", self.app)
        self.assertIn("Birmingham, UK", self.app)
        self.assertIn('\'<p class="hint">\' + (hint ? hint + " " : "") + CITY_HINT', self.app)

    def test_city_copy_is_worldwide_not_india_only(self):
        for phrase in ("Indian city", "Indian cities", "city in India", "cities in India"):
            self.assertNotIn(phrase, self.app, phrase)
            self.assertNotIn(phrase, _read("data.js"), phrase)
        # Diaspora circles stay -- they are core for moms abroad.
        data = load_data()
        names = {c["name"] for c in data["circles"]}
        self.assertTrue({"New to the US", "Parents visiting from India"} <= names, names)

    def test_no_us_city_in_user_visible_app_copy(self):
        for place in ("Mountain View", "Sunnyvale", "MOUNTAIN VIEW", "SUNNYVALE", "SF BAY", "El Camino", "Cuesta Park"):
            self.assertNotIn(place, self.app, place)

    def test_profile_rules_allow_owner_to_write_city_unchanged(self):
        # City rides on /profiles/{uid}; the owner-write rule permits it. Since
        # 2026-10-09 reads are owner-only too (profiles hold fullName + email).
        self.assertIn("match /profiles/{uid} {\n      allow read: if request.auth != null && request.auth.uid == uid;\n"
                      "      allow write: if request.auth != null && request.auth.uid == uid;", self.rules)

    def test_css_for_gate_and_strip(self):
        for sel in (".city-gate", ".city-strip", ".city-field"):
            self.assertIn(sel, self.css)
        self.assertNotIn(".waitlist", self.css)

    def test_rendered_behaviour_demo_and_real(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function boot(backend, seed) {
  const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
  if (seed) ls.store['aangan.demo.v1'] = JSON.stringify(seed);
  const w = { location: { hash: '#home', search: '', hostname: 'localhost' }, localStorage: ls,
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: backend, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
  w.window = w;
  vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
  return w.AANGAN;
}
function ok(c, msg) { if (!c) throw new Error(msg); }
for (const real of [false, true]) {
  const A = boot({ isReal: real }, null);
  const tag = real ? 'real: ' : 'demo: ';
  ok(A.city() === '', tag + 'fresh store must have no city');
  const ob = A.V['onboard/city']().html;
  ok(ob.includes('id="city-skip"') && ob.includes('optional') && ob.includes('<datalist id="city-suggestions">') && ob.includes('value="Pune"'), tag + 'onboarding city step: ' + ob);
  ok(ob.includes('value="San Jose, USA"') && ob.includes('value="London, UK"') && ob.includes('value="Dubai, UAE"') && ob.includes('placeholder="e.g. Pune, San Jose, London"') && ob.includes('Birmingham, UK'), tag + 'onboarding city step not global: ' + ob);
  const welcome = A.V.welcome().html;
  ok(!/Mountain View|Sunnyvale/.test(welcome), tag + 'welcome names a US city');
  ok(welcome.includes('Meetups in your city'), tag + 'welcome promise row');
  // Gated without a city ...
  for (const v of ['meetups', 'nearby']) {
    const h = A.V[v]().html;
    ok(h.includes('id="city-gate"') && h.includes('Add your city to use meetups') && h.includes('data-act="save-city"'), tag + v + ' not gated: ' + h);
    ok(!h.includes('data-act="rsvp"') && !h.includes('map-card'), tag + v + ' leaks content behind the gate');
  }
  // ... but the rest of the app is not.
  for (const v of ['home', 'ask', 'me']) ok(!A.V[v]().html.includes('city-gate'), tag + v + ' must not be gated');
  ok(A.V.me().html.includes('Not set · needed for meetups'), tag + 'Me shows empty city row');
  // Setting a city lifts the gate.
  A.saveCity('   Pune  ');
  ok(A.city() === 'Pune', tag + 'city trimmed: ' + A.city());
  const m = A.V.meetups().html;
  ok(!m.includes('city-gate') && m.includes('Pune') && m.includes('data-act="edit-city"'), tag + 'meetups after city: ' + m);
  ok(A.V.me().html.includes('>Pune<'), tag + 'Me shows city');
  if (real) {
    ok(m.includes('No meetups in Pune yet') && !m.includes('data-act="rsvp"') && !m.includes('Shoreline'), 'real meetups must be an honest empty state: ' + m);
    A.V.nearby(); // opt-in screen first
  } else {
    ok(m.includes('data-act="rsvp"') && m.includes('sample data (demo)'), 'demo meetups list: ' + m);
  }
  // Escaping + length cap.
  A.saveCity('<img src=x onerror=alert(1)>');
  const x = A.V.meetups().html + A.V.me().html;
  ok(!x.includes('<img src=x') && x.includes('&lt;img src=x'), tag + 'city not escaped');
  A.saveCity('x'.repeat(100)); ok(A.city().length === 40, tag + 'city not capped at 40');
  A.saveCity(''); ok(A.V.meetups().html.includes('city-gate'), tag + 'clearing city must re-gate');
}
// Real-mode nearby after opt-in: no fake moms, no sample map.
{
  const A = boot({ isReal: true }, { onboarded: true, city: 'Kochi', nearbyOn: true });
  const h = A.V.nearby().html;
  ok(h.includes('No moms nearby in Kochi yet') && !h.includes('map-card') && !h.includes('data-act="say-hi"'), 'real nearby: ' + h);
  const d = boot({ isReal: false }, { onboarded: true, city: 'Kochi', nearbyOn: true }).V.nearby().html;
  ok(d.includes('map-card') && d.includes('Sample neighbourhood map (demo data)') && !/MOUNTAIN VIEW|SUNNYVALE/.test(d), 'demo nearby map: ' + d);
}
// Migration: the old picker id is not a city.
ok(boot({ isReal: false }, { onboarded: true, city: 'mv-sv', waitlist: ['cupertino'] }).city() === '', 'mv-sv must migrate to empty');
ok(boot({ isReal: false }, { onboarded: true, city: ' Delhi ' }).city() === 'Delhi', 'existing free text kept');
// Firestore: write {city} only for a signed-in, onboarded mom.
(async () => {
  const calls = [];
  const be = (onb) => ({ isReal: true, user: { uid: 'u1' }, saveProfile(uid, doc) { calls.push([uid, doc]); return Promise.resolve(); } });
  boot(be(true), { onboarded: true }).saveCity('Indore');
  ok(calls.length === 1 && calls[0][0] === 'u1' && JSON.stringify(calls[0][1]) === '{"city":"Indore"}', 'firestore write: ' + JSON.stringify(calls));
  boot(be(false), { onboarded: false }).saveCity('Indore');
  ok(calls.length === 1, 'must not write a city-only profile before onboarding finishes');
  console.log('OK');
})().catch(e => { console.error(e.message); process.exit(1); });
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestSharedReactions(unittest.TestCase):
    """2026-10-09: reactions were localStorage-only, so other moms never saw a hug.
    Real mode now writes a per-mom marker + a +-1 counter in one batch; rules make
    each half depend on the other. These pin the shape; the two-user emulator run
    (state/scratch/aangan_e2e/reactions_e2e.py in Liquid) proves it live."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def test_backend_writes_marker_and_counter_in_one_batch(self):
        i = self.backend.index("Backend.setReaction = function")
        body = self.backend[i:self.backend.index("\n      };", i)]
        for s in ('"userReactions", uid, "marks"', "writeBatch(db)", "batch.set(markRef", "batch.delete(markRef)",
                  '"reactions." + r', "increment(on ? 1 : -1)", "batch.commit()"):
            self.assertIn(s, body, s)
        self.assertIn("Backend.listenMyReactions = function", self.backend)

    def test_rules_cross_check_marker_and_counter(self):
        r = self.rules
        self.assertIn("match /userReactions/{uid}/marks/{markId}", r)
        self.assertIn("function reactionIds() { return ['hug', 'been', 'helpful']; }", r)
        self.assertIn("na == nb + 1 && !exists(mark) && existsAfter(mark)", r)
        self.assertIn("na == nb - 1 && nb > 0 && exists(mark) && !existsAfter(mark)", r)
        self.assertIn("counterMoved(request.resource.data, 1)", r)
        self.assertIn("counterMoved(resource.data, -1)", r)
        self.assertIn("/userReactions/$(request.auth.uid)/marks/", r)  # never someone else's marker
        self.assertIn("allow update: if reactionBump(postId + '_' + replyId);", r)
        self.assertNotIn("toList()", r)  # not a Set method; the emulator warns and the rule never matches
        # New posts/replies can't be created with pre-stuffed counts.
        self.assertEqual(r.count("!('reactions' in request.resource.data)"), 2)
        # Markers are never edited in place and only their owner reads them.
        block = r[r.index("match /userReactions/{uid}/marks/{markId}"):]
        block = block[:block.index("\n    }")]
        self.assertNotIn("allow update", block)
        self.assertNotIn("allow write", block)

    def test_click_routes_real_mode_to_firestore_with_guard_and_rollback(self):
        self.assertIn('if (isRealMode()) { reactLive(el); break; }', self.app)
        i = self.app.index("function reactLive(el)")
        body = self.app[i:self.app.index("\n  }\n", i)]
        self.assertIn("if (reactState.pending[k] !== undefined) return;", body)  # double-tap guard
        self.assertIn("B.setReaction(uid, pid, rid, r, want)", body)
        self.assertIn("cache(!want)", body)  # rollback
        self.assertIn('failToast("save your reaction", null)(e)', body)

    def test_live_updates_patch_instead_of_rerender(self):
        self.assertIn("function patchReactions()", self.app)
        self.assertIn("if (same) patchReactions(); else rerender();", self.app)  # replies
        self.assertIn("else patchReactions();", self.app)  # posts
        self.assertIn("syncMarks();", self.app)
        self.assertIn("resetReactions();", self.app)
        self.assertIn('healListener("marks", "load your reactions", true)', self.app)

    def test_rendered_counts_demo_vs_real(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function boot(backend, seed) {
  const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
  if (seed) ls.store['aangan.demo.v1'] = JSON.stringify(seed);
  const w = { location: { hash: '#home', search: '', hostname: 'localhost' }, localStorage: ls,
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: backend, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
  w.window = w;
  vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
  return w.AANGAN;
}
function ok(c, msg) { if (!c) throw new Error(msg); }
const post = { id: 'x1', title: 'T', body: 'b', meta: 'Mom', hue: 'teal', replyCount: 0, reactions: { hug: 3 } };
// Real: shared count as stored (hers already included), pressed from her cached marker.
let h = boot({ isReal: true, user: { uid: 'u1' }, posts: [post] }, { onboarded: true, reactedLive: { 'x1:hug': true }, reactedLiveUid: 'u1' }).V.home().html;
ok(h.includes('aria-pressed="true" aria-label="Hug (3)"'), 'real pressed+shared count: ' + h);
ok(h.includes('aria-label="Been there (0)"'), 'real missing id = 0');
// Another mom's cache never marks this mom's button.
h = boot({ isReal: true, user: { uid: 'u2' }, posts: [post] }, { onboarded: true, reactedLive: { 'x1:hug': true }, reactedLiveUid: 'u1' }).V.home().html;
ok(h.includes('aria-pressed="false" aria-label="Hug (3)"'), 'other uid cache leaked: ' + h);
// Demo keeps local behaviour: fictional count + her toggle.
h = boot({ isReal: false }, { onboarded: true, reacted: { 'ppf1:hug': true } }).V.home().html;
ok(/aria-pressed="true" aria-label="Hug \(25\)"/.test(h), 'demo +1: ' + h);
console.log('OK');
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestFeedback(unittest.TestCase):
    """2026-10-09: "💬 Send feedback" -- write-only /feedback for signed-in moms,
    readable only by moderators. Live proof: state/scratch/aangan_e2e/feedback_e2e.py."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        cls.css = _read("styles.css")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def _block(self):
        i = self.rules.index("match /feedback/{feedbackId}")
        return self.rules[i:self.rules.index("\n    }", i)]

    def test_rules_create_only_shape_and_moderator_read(self):
        b = self._block()
        self.assertIn("request.resource.data.uid == request.auth.uid", b)
        self.assertIn("keys().hasOnly(['uid', 'text', 'kind', 'contactOk', 'page', 'ua', 'createdAt'])", b)
        self.assertIn("request.resource.data.text.size() >= 1", b)
        self.assertIn("request.resource.data.text.size() <= 1000", b)
        self.assertIn("in ['idea', 'bug', 'unsafe', 'other', null]", b)
        self.assertIn("allow read: if isModerator();", b)
        for bad in ("allow update", "allow delete", "allow write", "allow read: if request.auth != null"):
            self.assertNotIn(bad, b)

    def test_backend_write_has_exact_keys(self):
        i = self.backend.index("Backend.addFeedback = function")
        body = self.backend[i:self.backend.index("\n      };", i)]
        for k in ("uid: uid", "text:", "kind: kind || null", "contactOk: !!contactOk", "page:", "ua:", "createdAt: serverTimestamp()"):
            self.assertIn(k, body)
        self.assertIn('collection(db, "feedback")', body)

    def test_entry_points_and_copy(self):
        self.assertIn("💬 Send feedback", self.app)
        self.assertIn('var FEEDBACK_FOOT_TABS = ["home", "nearby", "meetups"];', self.app)
        self.assertIn('id="me-feedback"', self.app)
        self.assertIn('"Thank you 💛 We read every note."', self.app)
        self.assertIn('toast("Sign in to send feedback")', self.app)
        self.assertIn('maxlength="\' + FEEDBACK_MAX + \'"', self.app)
        self.assertIn("var FEEDBACK_MAX = 1000;", self.app)
        for k in ("Idea", "Bug", "Something felt unsafe", "Other"):
            self.assertIn('"%s"]' % k, self.app)
        self.assertNotIn("mailto:", self.app)  # no work email, no unread inbox
        self.assertIn(".feedback-foot", self.css)

    def test_send_is_debounced_and_keeps_text_on_error(self):
        i = self.app.index("function sendFeedback(el)")
        body = self.app[i:self.app.index("\n  }\n", i)]
        self.assertIn("if (fbDraft.sending) return;", body)
        self.assertIn("busy(el)", body)
        self.assertIn('failToast("send your feedback", el)(e)', body)
        ok_part = body[body.index(".then("):body.index(".catch(")]
        self.assertIn("fbDraft = freshFeedback()", ok_part)  # cleared only on success
        self.assertNotIn("freshFeedback", body[body.index(".catch("):])

    def test_text_is_escaped_in_sheet_and_mod_list(self):
        self.assertIn("esc(fbDraft.text)", self.app)
        self.assertIn("esc(f.text)", self.app)
        self.assertIn("B.listenFeedback(function (items)", self.app)
        self.assertIn("modState.unsubFb", self.app)

    def test_rendered_sheet_and_mod_list(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function ok(c, msg) { if (!c) throw new Error(msg); }
const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
const w = { location: { hash: '#me', search: '', hostname: 'localhost' }, localStorage: ls,
  document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
  Backend: { isReal: true, user: { uid: 'u1' } }, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
w.window = w;
vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
const me = w.AANGAN.V.me().html;
ok(me.includes('id="me-feedback"') && me.includes('Send feedback'), 'Me row: ' + me);
console.log('OK');
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestPrivacyTerms(unittest.TestCase):
    """2026-10-09: #privacy (Privacy & Terms) in plain language, linked from the
    welcome screen, the feedback footer and Me. It must never show an email
    address or a mailto: deletion requests go through Send feedback."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.css = _read("styles.css")

    def test_footer_and_css(self):
        body = self.app[self.app.index("function feedbackFoot()"):self.app.index("function feedbackSheetHtml()")]
        self.assertIn('href="#privacy" id="privacy-foot"', body)
        self.assertIn('id="feedback-open"', body)
        for sel in (".privacy-view", ".privacy-card", ".terms-line"):
            self.assertIn(sel, self.css)

    def test_not_legal_advice_note_is_code_comment_only(self):
        self.assertIn("// NOT LEGAL ADVICE", self.app)

    def test_rendered_privacy_welcome_me(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function ok(c, msg) { if (!c) throw new Error(msg); }
const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
const w = { location: { hash: '#privacy', search: '', hostname: 'localhost' }, localStorage: ls,
  document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
  Backend: { isReal: true, user: { uid: 'u1' } }, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
w.window = w;
vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
const pv = w.AANGAN.V.privacy();
ok(pv.tab === null, 'privacy is a tab-less page');
const h = pv.html;
['Who can join', '18 and over', 'What we store', 'Google Firebase', 'What other moms see', 'Anonymous mom',
 'Anonymous posts', 'Not medical advice', 'local emergency number', 'href="#safety"', 'Community rules',
 'No ads, selling or spam', 'medical misinformation', 'Moderators may remove', 'Delete my account',
 'within 30 days', 'Send feedback', 'never sell your data', 'Changes to these terms', 'Last updated: 9 October 2026'
].forEach(function (s) { ok(h.includes(s), 'missing: ' + s); });
ok(!h.includes('@'), 'privacy page must not contain any email address');
ok(!/mailto:/i.test(h), 'privacy page must not contain mailto');
ok(!/legal advice/i.test(h), 'legal-advice note belongs in a code comment, not on the page');
ok(!h.includes('Aangan'), 'old brand on privacy page');
const wel = w.AANGAN.V.welcome().html;
ok(wel.includes('id="welcome-terms"') && wel.includes('href="#privacy"') && wel.includes('By continuing you agree to our'), 'welcome terms line: ' + wel);
const me = w.AANGAN.V.me().html;
ok(me.includes('id="me-privacy"') && me.includes('href="#privacy"') && me.includes('Privacy &amp; Terms'), 'Me row: ' + me);
console.log('OK');
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestServedFromRoot(unittest.TestCase):
    """2026-10-09: the app moved from /web/ to the site root so the public link is
    https://sweta1910.github.io/momsakhi/#home. web/index.html is only a redirect
    stub that must keep the #route, so old .../web/#post-12 links still land."""

    def test_app_files_at_root(self):
        for name in ("index.html", "app.js", "backend.js", "data.js", "firebase-config.js", "styles.css"):
            self.assertTrue(os.path.exists(os.path.join(APP_DIR, name)), name)
        self.assertEqual(sorted(os.listdir(os.path.join(APP_DIR, "web"))), ["index.html"])

    def test_web_stub_redirects_and_keeps_hash(self):
        stub = _read("web/index.html")
        self.assertIn('location.replace("../" + location.hash)', stub)
        self.assertIn('<meta http-equiv="refresh" content="0; url=../">', stub)
        self.assertNotIn("app.js", stub)

    def test_tmp_is_ignored(self):
        with open(os.path.join(APP_DIR, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("tmp/", f.read().split())


def _png_size(path):
    """(width, height) from the PNG IHDR chunk -- stdlib only, no Pillow."""
    import struct
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path + " is not a PNG"
    return struct.unpack(">II", head[16:24])


class TestInstallablePWA(unittest.TestCase):
    """2026-10-09: MomSakhi is installable (Add to Home Screen). manifest +
    icons + a shell-only service worker that must NEVER intercept Firebase,
    Firestore, Google sign-in, gstatic or any cross-origin request (the live
    feed has to stay live), and that picks up a new deploy (network-first HTML,
    VERSION tied to the ?v= cache string, skipWaiting + clients.claim)."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read("index.html")
        cls.sw = _read("sw.js")
        cls.app = _read("app.js")
        with open(os.path.join(APP_DIR, "manifest.webmanifest"), encoding="utf-8") as f:
            cls.manifest = json.load(f)

    def test_manifest_fields(self):
        m = self.manifest
        self.assertEqual(m["name"], "MomSakhi")
        self.assertEqual(m["short_name"], "MomSakhi")
        self.assertEqual(m["description"], load_data()["brand"]["tagline"])
        self.assertEqual(m["start_url"], "./#home")
        self.assertEqual(m["scope"], "./")
        self.assertEqual(m["display"], "standalone")
        css = _read("styles.css")
        for key in ("theme_color", "background_color"):
            self.assertRegex(m[key], r"^#[0-9A-Fa-f]{6}$")
            self.assertIn(m[key].upper(), css.upper(), key + " must come from the styles.css palette")
        self.assertIn('<meta name="theme-color" content="%s">' % m["theme_color"], self.html)

    def test_icons_exist_with_right_sizes(self):
        purposes = {}
        for icon in self.manifest["icons"]:
            path = os.path.join(APP_DIR, icon["src"])
            self.assertTrue(os.path.exists(path), icon["src"])
            w, h = _png_size(path)
            self.assertEqual("%dx%d" % (w, h), icon["sizes"], icon["src"])
            self.assertEqual(icon["type"], "image/png")
            purposes.setdefault(icon["purpose"], set()).add(icon["sizes"])
        self.assertEqual(purposes["any"], {"192x192", "512x512"})
        self.assertEqual(purposes["maskable"], {"512x512"})
        self.assertEqual(_png_size(os.path.join(APP_DIR, "icons/apple-touch-icon.png")), (180, 180))

    def test_head_link_and_meta_tags(self):
        for tag in ('<link rel="manifest" href="manifest.webmanifest">',
                    '<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png">',
                    '<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<meta name="apple-mobile-web-app-title" content="MomSakhi">',
                    '<meta name="mobile-web-app-capable" content="yes">'):
            self.assertIn(tag, self.html)

    def test_sw_registered_relative_with_scope(self):
        self.assertIn('navigator.serviceWorker.register("sw.js", { scope: "./" })', self.app)
        self.assertIn('window.addEventListener("beforeinstallprompt"', self.app)

    def test_sw_version_matches_cache_string(self):
        v = set(re.findall(r'\?v=([\da-f]{7})"', self.html))
        self.assertEqual(len(v), 1)
        self.assertIn('var VERSION = "%s";' % v.pop(), self.sw,
                      "bump sw.js VERSION together with the ?v= cache string")

    def test_sw_never_touches_firebase_google_or_cross_origin(self):
        sw = self.sw
        self.assertIn("if (url.origin !== self.location.origin) return;", sw)
        self.assertIn('if (req.method !== "GET") return;', sw)
        never = re.search(r"var NEVER = /(.+)/i;", sw).group(1)
        for host in ("firestore", "googleapis", "gstatic", "firebase", "identitytoolkit", "securetoken"):
            self.assertIn(host, never)
        # The precache list is same-origin relative paths only.
        shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
        self.assertNotRegex(shell, r"https?:|//|firestore|googleapis|gstatic|firebase\.")
        for f in ("index.html", "app.js", "backend.js", "styles.css", "manifest.webmanifest"):
            self.assertIn(f, shell)
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", sw, flags=re.S)
        self.assertNotIn("googleapis.com", code.replace("googleapis|", ""))

    def test_sw_picks_up_new_deploys(self):
        self.assertIn("self.skipWaiting()", self.sw)
        self.assertIn("self.clients.claim()", self.sw)
        self.assertIn("if (isHtml) { event.respondWith(networkFirst(req)); return; }", self.sw)
        self.assertIn("caches.delete(k)", self.sw)

    def test_sw_js_syntax(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        r = subprocess.run([node, "--check", os.path.join(APP_DIR, "sw.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_install_hint_once_on_home_after_sign_in(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function ok(c, msg) { if (!c) throw new Error(msg); }
const IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36';
function boot(ua, ls, backend, standalone, onboarded) {
  ls.store['aangan.demo.v1'] = JSON.stringify({ onboarded: onboarded !== false });
  const w = { location: { hash: '#home', search: '', hostname: 'localhost' }, localStorage: ls,
    navigator: { userAgent: ua, standalone: !!standalone },
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: backend, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
  w.window = w;
  vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
  return w.AANGAN;
}
function newLs() { return { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } }; }
const signedIn = { isReal: true, user: { uid: 'u1' }, posts: [] };
let ls = newLs();
let A = boot(IOS, ls, signedIn);
let h = A.V.home().html;
ok(h.includes('id="install-hint"') && h.includes('Tap Share → Add to Home Screen.'), 'iOS tip on home: ' + h);
ok(A.V.home().html.includes('id="install-hint"'), 'stays for the rest of this session');
ok(ls.store['aangan.installHint.v1'] === '1', 'marked shown');
ok(!boot(IOS, ls, signedIn).V.home().html.includes('install-hint'), 'never shown twice');
ok(!A.V.welcome().html.includes('install-hint'), 'never on welcome');
ok(!boot(IOS, newLs(), { isReal: true, user: null, posts: [] }).V.home().html.includes('install-hint'), 'not before sign-in');
ok(!boot(IOS, newLs(), signedIn, true).V.home().html.includes('install-hint'), 'not when installed');
ok(!boot(ANDROID, newLs(), signedIn).V.home().html.includes('install-hint'), 'Android waits for beforeinstallprompt');
console.log('OK');
""" % WEB_DIR
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)


class TestInAppBrowserWarning(unittest.TestCase):
    """2026-10-09: Google blocks OAuth in embedded webviews (403
    disallowed_useragent). On Instagram/Facebook/Messenger/LinkedIn/Snapchat/
    TikTok/LINE in-app browsers and generic Android WebView the welcome screen
    shows "To sign in, open MomSakhi in Chrome or Safari" with Copy link (and
    Open in Chrome on Android). Real browsers and WhatsApp (no reliable UA
    marker) must NOT be warned. A webview-type sign-in error shows the same card."""

    def _run(self, body):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
function ok(c, msg) { if (!c) throw new Error(msg); }
const LOC = { hash: '#welcome', search: '', hostname: 'sweta1910.github.io', host: 'sweta1910.github.io',
  protocol: 'https:', origin: 'https://sweta1910.github.io', pathname: '/momsakhi/' };
function boot(ua) {
  const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
  const w = { location: Object.assign({}, LOC), localStorage: ls, navigator: { userAgent: ua },
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: { isReal: true, user: null, posts: [] }, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout };
  w.window = w;
  vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
  return w.AANGAN;
}
const UA = {
  instagramIOS: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 339.0.3.12.91 (iPhone15,2; iOS 17_5; en_IN; en; scale=3.00; 1179x2556; 619476133)',
  fbAndroid: 'Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0.6668.81 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/484.0.0.53.105;]',
  fbIOS: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/484.0.0.39.109;FBBV/650000000;FBDV/iPhone15,2;FBMD/iPhone;FBSN/iOS;FBSV/17.5;FBSS/3;FBCR/;FBID/phone;FBLC/en_US;FBOP/5]',
  linkedin: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [LinkedInApp]/9.30.1',
  snapchat: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Snapchat/13.10.0.41 (like Safari/8618.2.12.10.3, panda)',
  tiktok: 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230901.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 trill_310503 BytedanceWebview/d8a21c6 musical_ly_2023105030 JsSdk/1.0',
  androidWebView: 'Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0.6668.81 Mobile Safari/537.36',
  androidChrome: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.81 Mobile Safari/537.36',
  iosSafari: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  iosChrome: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0.6668.69 Mobile/15E148 Safari/604.1',
  desktopChrome: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
  whatsappLike: 'Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.81 Mobile Safari/537.36',
  whatsappIOS: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
};
%s
console.log('OK');
"""
        r = subprocess.run([node, "-e", harness % (WEB_DIR, body)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)

    def test_ua_detection(self):
        self._run(r"""
const A = boot('');
const expect = { instagramIOS: ['Instagram', 'ios'], fbAndroid: ['Facebook', 'android'], fbIOS: ['Facebook', 'ios'],
  linkedin: ['LinkedIn', 'ios'], snapchat: ['Snapchat', 'ios'], tiktok: ['TikTok', 'android'], androidWebView: ['', 'android'] };
Object.keys(expect).forEach(function (k) {
  const r = A.inAppBrowser(UA[k]);
  ok(r && r.name === expect[k][0] && r.os === expect[k][1], k + ' -> ' + JSON.stringify(r));
});
['androidChrome', 'iosSafari', 'iosChrome', 'desktopChrome', 'whatsappLike', 'whatsappIOS'].forEach(function (k) {
  ok(A.inAppBrowser(UA[k]) === null, k + ' must not be warned');
});
ok(A.inAppBrowser('') === null && A.inAppBrowser(undefined) === null, 'empty UA');
""")

    def test_webview_auth_errors_and_links(self):
        self._run(r"""
const A = boot('');
ok(A.isWebviewAuthError({ code: 'auth/disallowed-useragent' }), 'disallowed-useragent');
ok(A.isWebviewAuthError({ code: 'auth/web-storage-unsupported' }), 'web storage');
ok(A.isWebviewAuthError({ code: 'auth/operation-not-supported-in-this-environment' }), 'op not supported');
ok(A.isWebviewAuthError({ code: 'auth/internal-error', message: 'Error 403: disallowed_useragent' }), 'message match');
ok(!A.isWebviewAuthError({ code: 'auth/popup-closed-by-user' }) && !A.isWebviewAuthError(null), 'normal errors');
ok(A.appLink(LOC) === 'https://sweta1910.github.io/momsakhi/', A.appLink(LOC));
ok(A.chromeIntentUrl(LOC) === 'intent://sweta1910.github.io/momsakhi/#Intent;scheme=https;package=com.android.chrome;end', A.chromeIntentUrl(LOC));
const local = { host: 'localhost:8765', protocol: 'http:', pathname: '/', search: '' };
ok(A.appLink(local) === 'http://localhost:8765/', A.appLink(local));
ok(A.chromeIntentUrl(local) === 'intent://localhost:8765/#Intent;scheme=http;package=com.android.chrome;end', 'built from location');
""")

    def test_welcome_card_per_browser(self):
        self._run(r"""
let h = boot(UA.instagramIOS).V.welcome().html;
ok(h.includes('id="iab-card"') && h.includes('To sign in, open MomSakhi in Chrome or Safari'), 'IG card: ' + h);
ok(h.includes("inside Instagram's built-in browser") && h.includes('Open in Safari') && h.includes('id="iab-copy"'), 'IG iOS copy');
ok(h.includes('value="https://sweta1910.github.io/momsakhi/"'), 'link field');
ok(!h.includes('id="iab-chrome"'), 'no Chrome intent on iOS');
ok(h.indexOf('id="iab-card"') < h.indexOf('id="google-signin"'), 'card above the Google button');
h = boot(UA.fbAndroid).V.welcome().html;
ok(h.includes('id="iab-chrome"') && h.includes('href="intent://sweta1910.github.io/momsakhi/#Intent;scheme=https;package=com.android.chrome;end"'), 'FB Android intent: ' + h);
['androidChrome', 'iosSafari', 'whatsappLike', 'desktopChrome'].forEach(function (k) {
  ok(!boot(UA[k]).V.welcome().html.includes('iab-card'), k + ' shows no card');
});
// Sign-in failed with a webview error in an unrecognised browser -> same card.
const A = boot(UA.whatsappLike);
try { A.showSignInBlocked(); } catch (e) { /* render() needs a DOM; the flag is what matters */ }
h = A.V.welcome().html;
ok(h.includes('id="iab-card"') && h.includes("inside this app's built-in browser") && h.includes('id="iab-chrome"'), 'after blocked sign-in: ' + h);
""")

    def test_sign_in_paths_route_webview_errors_to_card(self):
        app = _read("app.js")
        self.assertEqual(app.count("if (isWebviewAuthError(e))"), 2, "popup path and redirect path")
        self.assertIn('case "copy-app-link"', app)
        self.assertIn("navigator.clipboard.writeText(appUrl).then(copied, selectCopy)", app)
        self.assertIn('document.execCommand("copy")', app)
        self.assertNotIn("WhatsApp", re.search(r"var IAB_RE = (.*);", app).group(1))
        for sel in (".iab-card", ".iab-actions", ".iab-link"):
            self.assertIn(sel, _read("styles.css"))


if __name__ == "__main__":
    unittest.main()


class TestHelplines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")

    def test_derive_country(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        
        # We can extract the deriveCountry function and test it
        start_idx = self.app.find("function deriveCountry")
        end_idx = self.app.find("var HELPLINES =")
        derive_func = self.app[start_idx:end_idx]
        
        harness = derive_func + """
        const cases = [
            ["Pune", "IN"],
            ["Mumbai", "IN"],
            ["San Jose, USA", "US"],
            ["Edison, NJ, USA", "US"],
            ["London, UK", "UK"],
            ["Dubai, UAE", "UAE"],
            ["Toronto, Canada", "CA"],
            ["Sydney, Australia", "AU"],
            ["Singapore", "SG"],
            ["Berlin, Germany", "DE"],
            ["Auckland, New Zealand", "NZ"],
            ["Doha, Qatar", "QA"],
            ["Unknown City", null],
            ["", null],
            [null, null]
        ];
        cases.forEach(c => {
            const res = deriveCountry(c[0]);
            if (res !== c[1]) {
                console.error("Failed for " + c[0] + ": expected " + c[1] + " got " + res);
                process.exit(1);
            }
        });
        console.log("ok");
        """
        import subprocess
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_safety_rendering_by_country(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        
        harness = """
        const fs = require('fs'), path = require('path'), vm = require('vm');
        const webDir = '""" + WEB_DIR + """';
        const dataJs = fs.readFileSync(path.join(webDir, 'data.js'), 'utf8');
        const appJs = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');
        
        function boot(city, safetyCountry) {
            const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
            const w = { 
                location: { hash: '#home', search: '', hostname: 'localhost' }, 
                localStorage: ls,
                document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
                Backend: { isReal: false }, console: console, setTimeout: setTimeout, clearTimeout: clearTimeout 
            };
            w.window = w;
            vm.runInContext(dataJs, vm.createContext(w)); 
            w.localStorage.store['aangan.demo.v1'] = JSON.stringify({ city: city, safetyCountry: safetyCountry });
            vm.runInContext(appJs, w);
            return w.AANGAN.V.safety().html;
        }
        
        const htmlIN = boot('Pune', null);
        if (!htmlIN.includes('14416') || htmlIN.includes('988')) {
            console.error('India rendering failed'); process.exit(1);
        }
        
        const htmlUS = boot('San Jose, USA', null);
        if (!htmlUS.includes('988') || htmlUS.includes('14416')) {
            console.error('US rendering failed'); process.exit(1);
        }
        
        const htmlUK = boot('London, UK', null);
        if (!htmlUK.includes('111') || !htmlUK.includes('116 123')) {
            console.error('UK rendering failed'); process.exit(1);
        }
        
        const htmlUnknown = boot('Unknown City', null);
        if (!htmlUnknown.includes('findahelpline.com') || !htmlUnknown.includes('local emergency number')) {
            console.error('Unknown rendering failed'); process.exit(1);
        }
        
        const htmlOverride = boot('Pune', 'US');
        if (!htmlOverride.includes('988') || htmlOverride.includes('14416')) {
            console.error('Override rendering failed'); process.exit(1);
        }
        
        console.log("ok");
        """
        import subprocess
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
