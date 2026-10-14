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
        # 2026-10-12: the closed-beta invite screen uses the same centred layout.
        self.assertIn('var isOnboarding = r.name === "welcome" || r.name.indexOf("onboard/") === 0 || r.name === "invite";', js)
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
        self.assertEqual(self.backend.count("onSnapshot(q, function(snap)"), 5)  # + feedback, invites (moderators)
        self.assertEqual(self.backend.count("if (onError) onError(e);"), 6)  # posts, replies, reports, my reactions, feedback, invites (mods)
        # 2026-10-12 closed beta: no listener for a signed-in non-member either.
        self.assertIn("if (!B.user || !hasAccess()) { B.posts = []; return; }", self.app)

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
        self.assertIn('"Invite-only during the beta · sign in with Google, then enter your invite code"', self.app)
        self.assertIn('"Prototype · all people, posts and places are fictional demo data"', self.app)
        self.assertIn('(isRealMode() ? "Invite-only during the beta · sign in with Google, then enter your invite code" : "Prototype · all people, posts and places are fictional demo data")', self.app)

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
    if (!welcome.includes('Invite-only during the beta · sign in with Google, then enter your invite code')) {
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
        # 2026-10-12: get('uid', null) because anonymous posts/replies have no uid key;
        # their author proves ownership via the private /postAuthors record instead.
        self.assertEqual(self.rules.count("(isModerator() || resource.data.get('uid', null) == request.auth.uid)"), 2)
        self.assertEqual(self.rules.count("isAnonAuthor(/databases/$(database)/documents/postAuthors/$(postId)"), 2)

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
        # 2026-10-12 closed beta: owner-only AND members-only.
        self.assertIn("match /profiles/{uid} {\n      allow read: if request.auth != null && request.auth.uid == uid && isMember();\n"
                      "      allow write: if request.auth != null && request.auth.uid == uid && isMember();", self.rules)

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


class TestEditNickname(unittest.TestCase):
    """2026-10-12: the nickname could only be set during onboarding, so a mom who
    typed a placeholder ("test") was stuck with it. The Me profile card now has an
    "Edit nickname" control opening a sheet; saves are trimmed, capped at 20 like
    onboarding, never blank, and in real mode go through Backend.saveProfile(uid,
    profileDoc()) -- the onboarding path -- reverting on a failed write."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()

    def test_me_tab_has_edit_control_and_sheet(self):
        self.assertIn('data-act="edit-nick" id="me-edit-nick"', self.app)
        self.assertIn('case "edit-nick":', self.app)
        self.assertIn('case "save-nick":', self.app)
        self.assertIn("var NICK_MAX = 20;", self.app)
        # Onboarding keeps the same cap.
        self.assertIn('id="nick" maxlength="20"', self.app)
        # Sheet input must NOT reuse data-input="nick" (that writes the store per keystroke,
        # which would make Cancel a no-op).
        self.assertIn('data-input="nick-edit"', self.app)
        self.assertIn('k === "nick-edit"', self.app)

    def test_save_goes_through_save_profile_with_full_doc(self):
        i = self.app.index("function saveNickname(")
        body = self.app[i:self.app.index("\n  }\n", i)]
        self.assertIn("B.saveProfile(B.user.uid, profileDoc())", body)
        self.assertIn("store.profile.nickname = prev", body)  # revert on failure
        self.assertIn('failToast("save your nickname", btn)', body)

    def test_profile_rules_allow_owner_nickname_write_unchanged(self):
        # 2026-10-12 closed beta: owner-only AND members-only.
        self.assertIn("match /profiles/{uid} {\n      allow read: if request.auth != null && request.auth.uid == uid && isMember();\n"
                      "      allow write: if request.auth != null && request.auth.uid == uid && isMember();", self.rules)

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
  // Forgiving fake element: the failure path re-renders, which touches the DOM.
  const el = { textContent: '', hidden: true, innerHTML: '', style: {}, scrollTop: 0, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; }, addEventListener() {},
    appendChild() {}, insertAdjacentHTML() {}, focus() {}, scrollTo() {}, closest() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; } };
  const w = { location: { hash: '#me', search: '', hostname: 'localhost' }, localStorage: ls,
    document: { addEventListener() {}, querySelector() { return el; }, querySelectorAll() { return []; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: backend, console: { log() {}, error() {}, warn() {} }, setTimeout: setTimeout, clearTimeout: clearTimeout };
  w.window = w;
  vm.runInContext(dataJs, vm.createContext(w)); vm.runInContext(appJs, w);
  w.AANGAN._ls = ls; w.AANGAN._el = el;
  return w.AANGAN;
}
function ok(c, msg) { if (!c) throw new Error(msg); }
const seed = { onboarded: true, city: 'Pune', profile: { nickname: 'test', fullName: '', email: '', anonDefault: false, stages: ['Toddler'], langs: ['Hindi'] } };
(async () => {
  for (const real of [false, true]) {
    const tag = real ? 'real: ' : 'demo: ';
    const A = boot({ isReal: real }, seed);
    const me = A.V.me().html;
    ok(me.includes('id="me-edit-nick"') && me.includes('Edit nickname'), tag + 'Me tab has no edit control: ' + me);
    // Blank / whitespace-only names are rejected and change nothing.
    ok(A.cleanNick('   ') === '', tag + 'blank must clean to empty');
    ok((await A.saveNickname('')) === null && (await A.saveNickname('   ')) === null, tag + 'blank must be rejected');
    ok(A.nickname() === 'test', tag + 'blank changed nickname: ' + A.nickname());
    // Trimmed + capped at 20, like onboarding.
    ok(A.cleanNick('x'.repeat(30)).length === 20, tag + 'not capped at 20');
    ok(A.cleanNick('  Asha  ') === 'Asha', tag + 'not trimmed');
    if (!real) {
      ok((await A.saveNickname('  Asha  ')) === 'Asha' && A.nickname() === 'Asha', 'demo save: ' + A.nickname());
      ok(JSON.parse(A._ls.store['aangan.demo.v1']).profile.nickname === 'Asha', 'demo save not persisted locally');
      ok(A.V.me().html.includes('<h2>Asha</h2>'), 'Me not showing new name');
      // Escaped on render.
      await A.saveNickname('<b>x</b>');
      ok(A.V.me().html.includes('&lt;b&gt;x&lt;/b&gt;') && !A.V.me().html.includes('<b>x</b>'), 'nickname not escaped');
    }
  }
  // Real mode: one saveProfile(uid, profileDoc()) with the new name (and city kept).
  const calls = [];
  const be = (fail) => ({ isReal: true, user: { uid: 'u1' },
    saveProfile(uid, doc) { calls.push([uid, JSON.parse(JSON.stringify(doc))]); return fail ? Promise.reject({ code: 'permission-denied' }) : Promise.resolve(); } });
  const R = boot(be(false), seed);
  ok((await R.saveNickname(' Sweta ')) === 'Sweta', 'real save result');
  ok(calls.length === 1 && calls[0][0] === 'u1' && calls[0][1].nickname === 'Sweta' && calls[0][1].city === 'Pune' && Array.isArray(calls[0][1].stages), 'real saveProfile call: ' + JSON.stringify(calls));
  ok(JSON.parse(R._ls.store['aangan.demo.v1']).profile.nickname === 'Sweta', 'real save not persisted locally');
  // Blank never reaches Firestore.
  await R.saveNickname('   ');
  ok(calls.length === 1, 'blank name must not call saveProfile');
  // Failed write: toast + revert to the old name, locally too.
  const F = boot(be(true), seed);
  ok((await F.saveNickname('Nope')) === null, 'failed save must resolve null');
  ok(F.nickname() === 'test' && JSON.parse(F._ls.store['aangan.demo.v1']).profile.nickname === 'test', 'failed save not reverted: ' + F.nickname());
  ok(/Couldn't save your nickname yet \(permission-denied\)/.test(F._el.textContent), 'no failure toast: ' + F._el.textContent);
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
        self.assertIn("allow update: if isMember() && reactionBump(postId + '_' + replyId);", r)
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
 'within 30 days', 'Send feedback', 'never sell your data', 'Changes to these terms', 'Last updated: 12 October 2026'
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
    Open in Chrome on Android). Real browsers and Custom Tabs / SFSafariViewController
    (how WhatsApp usually opens links: no app token in the UA) must NOT be warned;
    since 2026-10-14 webviews that name WhatsApp/Telegram/X/Pinterest are.
    A webview-type sign-in error shows the same card."""

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
        # 2026-10-14: both paths (popup + getRedirectResult) go through ONE handler,
        # which sends webview errors to the card and everything else to a message.
        self.assertEqual(app.count("if (isWebviewAuthError(e))"), 1, "single sign-in error handler")
        self.assertIn(".catch(function(e) { handleSignInError(e, btn); })", app)
        self.assertIn(".catch(function (e) { handleSignInError(e, null); })", app)
        self.assertIn('case "copy-app-link"', app)
        self.assertIn("navigator.clipboard.writeText(appUrl).then(copied, selectCopy)", app)
        self.assertIn('document.execCommand("copy")', app)
        iab = re.search(r"var IAB_RE = (.*);", app).group(1)
        for token in ("WhatsApp", "Telegram", "Twitter", "Pinterest"):
            self.assertIn(token, iab)
        self.assertNotIn("GSA", iab)
        for sel in (".iab-card", ".iab-actions", ".iab-link", ".signin-error"):
            self.assertIn(sel, _read("styles.css"))

    def test_app_token_webviews_warned_custom_tabs_not(self):
        # WhatsApp/Telegram/X/Pinterest webviews name the app in the UA; Custom
        # Tabs / SFSafariViewController do not (whatsappLike/whatsappIOS above).
        self._run(r"""
const A = boot('');
const more = {
  'WhatsApp': 'Mozilla/5.0 (Linux; Android 14; SM-A546E Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0.6668.81 Mobile Safari/537.36 WhatsApp/2.24.20.89',
  'Telegram': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Telegram-iOS/11.1',
  'X (Twitter)': 'Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0 Mobile Safari/537.36 TwitterAndroid',
  'Pinterest': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [Pinterest/iOS]'
};
Object.keys(more).forEach(function (name) {
  const r = A.inAppBrowser(more[name]);
  ok(r && r.name === name, name + ' -> ' + JSON.stringify(r));
});
const h = boot(more.WhatsApp).V.welcome().html;
ok(h.includes('id="iab-card"') && h.includes("inside WhatsApp's built-in browser") && h.includes('id="iab-chrome"'), 'WhatsApp card: ' + h);
ok(A.inAppBrowser('Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129 Mobile Safari/537.36 GSA/15.40') === null, 'Google app not warned');
""")


class TestGoogleOnlySignIn(unittest.TestCase):
    """2026-10-14: a real beta mom tapped the demo-leftover "Continue with phone"
    (fake number, fake code) and got stuck. Real mode is Google-only: no phone
    button, no "I already have an account", no phone form on the sign-in step,
    and every Google sign-in failure shows a kind message saying what to do.
    The prototype (demo mode) keeps the phone path."""

    def _run(self, body):
        TestInAppBrowserWarning._run(self, body)

    def test_welcome_real_mode_google_only_demo_keeps_phone(self):
        self._run(r"""
const real = boot(UA.androidChrome).V.welcome().html;
ok(real.includes('id="google-signin"') && real.includes('Continue with Google'), 'google button');
['id="get-started"', 'id="have-account"', 'Continue with phone', 'start-phone-onboard', 'auth-divider'].forEach(function (s) {
  ok(!real.includes(s), 'real welcome must not include ' + s);
});
ok(real.includes('Invite-only during the beta · sign in with Google, then enter your invite code'), 'mode line');
ok(!/phone/i.test(real.replace(/iPhone/g, '')), 'no phone claims on real welcome');
""")

    def test_verify_step_real_mode_has_no_phone_form(self):
        self._run(r"""
const h = boot(UA.androidChrome).V['onboard/verify']().html;
ok(h.includes('id="verify-google"'), 'google button on sign-in step: ' + h);
['555-0142', 'id="verify-phone"', 'Send code', 'Verify your phone'].forEach(function (s) { ok(!h.includes(s), 'real verify must not include ' + s); });
ok(h.includes('id="enter-app" disabled'), 'cannot enter without Google');
""")

    def test_sign_in_failure_messages(self):
        self._run(r"""
const A = boot(UA.androidChrome);
const m = A.signInFailMessage;
['auth/popup-closed-by-user', 'auth/popup-blocked', 'auth/cancelled-popup-request'].forEach(function (c) {
  ok(m({ code: c }).includes('Tap Continue with Google again and allow the pop-up'), c);
});
ok(m({ code: 'auth/network-request-failed' }).includes('Check your internet connection'), 'network');
ok(m({ code: 'auth/unauthorized-domain' }) === "Sign-in didn't work (unauthorized-domain). Try opening this link in Chrome or Safari.", m({ code: 'auth/unauthorized-domain' }));
ok(m(null).includes('Try opening this link in Chrome or Safari'), 'unknown error');
""")

    def test_handlers_guarded_and_phone_leftovers_cleared(self):
        app = _read("app.js")
        for act in ("start-phone-onboard", "skip-onboarding", "verify-phone"):
            block = app.split('case "%s":' % act, 1)[1][:200]
            self.assertIn("if (isRealMode()) { signInWithGoogle(null, el); break; }", block, act)
        self.assertIn('if (store.authMethod === "phone" || (store.verify && store.verify.phone)) {', app)
        self.assertIn('signInErrorCard() +', app)


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
        if (!htmlIN.includes('14416') || !htmlIN.includes('112') || htmlIN.includes('988')) {
            console.error('India rendering failed'); process.exit(1);
        }
        
        const htmlUS = boot('San Jose, USA', null);
        if (!htmlUS.includes('988') || htmlUS.includes('14416')) {
            console.error('US rendering failed'); process.exit(1);
        }
        
        const htmlUK = boot('London, UK', null);
        if (!htmlUK.includes('111') || !htmlUK.includes('116 123') || !htmlUK.includes('999')) {
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


class TestPreInviteSafety(unittest.TestCase):
    """2026-10-12 pre-invite safety fixes:
    1. anonymous posts/replies carry NO uid in the public doc; authorship lives in
       moderator-only /postAuthors (written in the same batch, rules-enforced);
    2. no "women-only & verified" claims (sign-in is not identity verification);
    3. real mode never shows data.js people/events/chats (Nearby, Meetups, Chats, DMs);
    4. a static privacy/index.html served at /privacy/, in sync with #privacy.
    Live proof against the emulator: ~/liquid/state/scratch/aangan_e2e/anon_e2e.py."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        cls.data = _read("data.js")
        cls.index = _read("index.html")
        cls.sw = _read("sw.js")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()
        cls.privacy_path = os.path.join(APP_DIR, "privacy", "index.html")

    def _node_run(self, harness):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)
        return r.stdout

    # ---- 1. anonymity
    def test_anon_payloads_have_no_uid(self):
        self._node_run(r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const src = fs.readFileSync(path.join(%r, 'backend.js'), 'utf8');
const w = { console: console }; w.window = w;   // no FIREBASE_CONFIG -> demo branch, pure helpers still exported
vm.runInContext(src, vm.createContext(w));
const B = w.Backend;
function ok(c, m) { if (!c) throw new Error(m); }
const TS = { ts: 1 };
const anon = B._postPayload('uid-123', 'Meera', true, 'sleep', 'T', 'Body', 'Mom of a toddler', 'teal', TS);
ok(!('uid' in anon), 'anon post carries uid: ' + JSON.stringify(anon));
ok(anon.author === null && anon.anon === true, 'anon post author/anon: ' + JSON.stringify(anon));
ok(!JSON.stringify(anon).includes('uid-123'), 'anon post leaks the uid value anywhere');
const named = B._postPayload('uid-123', 'Meera', false, null, 'T', 'Body', 'Mom', 'teal', TS);
ok(named.uid === 'uid-123' && named.author === 'Meera' && named.anon === false, 'named post: ' + JSON.stringify(named));
const ar = B._replyPayload('uid-123', null, true, 'hi', 'teal', TS);
ok(!('uid' in ar) && ar.author === null && !JSON.stringify(ar).includes('uid-123'), 'anon reply: ' + JSON.stringify(ar));
const nr = B._replyPayload('uid-123', 'Meera', false, 'hi', 'teal', TS);
ok(nr.uid === 'uid-123', 'named reply keeps uid');
const rec = B._authorRecord('uid-123', TS);
ok(JSON.stringify(Object.keys(rec).sort()) === '["createdAt","uid"]' && rec.uid === 'uid-123', 'author record: ' + JSON.stringify(rec));
// Keys a post may have must match the rules' hasOnly list.
console.log(JSON.stringify(Object.keys(named).sort()));
console.log('OK');
""" % WEB_DIR)

    def test_backend_anon_writes_author_record_in_same_batch(self):
        i = self.backend.index("Backend.addPost = function")
        body = self.backend[i:self.backend.index("Backend.addReport = function")]
        self.assertIn("if (!data.anon) return addDoc(collection(db, \"posts\"), data);", body)
        self.assertIn('batch.set(doc(db, "postAuthors", postRef.id), authorRecord(uid, serverTimestamp()));', body)
        self.assertIn('batch.set(doc(db, "postAuthors", postId, "replies", replyRef.id), authorRecord(uid, serverTimestamp()));', body)
        self.assertEqual(body.count("batch.commit()"), 2)
        self.assertNotIn("uid: uid,", body)  # uid is added only for named posts, inside postPayload

    def test_rules_anon_has_no_uid_and_private_author_record(self):
        posts = self.rules[self.rules.index("match /posts/{postId}"):self.rules.index("match /postAuthors/{postId}")]
        self.assertEqual(posts.count("!('uid' in request.resource.data)"), 2)  # posts + replies
        self.assertIn("keys().hasOnly(['uid', 'author', 'anon', 'circle', 'title', 'body', 'meta', 'hue', 'createdAt', 'replyCount'])", posts)
        self.assertIn("keys().hasOnly(['uid', 'author', 'anon', 'body', 'hue', 'createdAt'])", posts)
        self.assertIn("getAfter(/databases/$(database)/documents/postAuthors/$(postId)).data.uid == request.auth.uid", posts)
        self.assertIn("getAfter(/databases/$(database)/documents/postAuthors/$(postId)/replies/$(replyId)).data.uid == request.auth.uid", posts)
        pa = self.rules[self.rules.index("match /postAuthors/{postId}"):self.rules.index("match /reports/{reportId}")]
        self.assertEqual(pa.count("allow read: if isModerator() || (request.auth != null && resource.data.uid == request.auth.uid);"), 2)
        self.assertNotIn("allow update", pa)
        self.assertNotIn("allow write", pa)
        self.assertNotIn("allow read: if request.auth != null;", pa)
        helper = self.rules[self.rules.index("function authorRecordOk(target)"):self.rules.index("function isAnonAuthor(record)")]
        for s in ("keys().hasOnly(['uid', 'createdAt'])", "request.resource.data.uid == request.auth.uid",
                  "!exists(target) && existsAfter(target)", "getAfter(target).data.get('anon', false) == true"):
            self.assertIn(s, helper)

    def test_backend_post_keys_match_rules(self):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        src = r"""
const fs = require('fs'), vm = require('vm'); const w = {console}; w.window = w;
vm.runInContext(fs.readFileSync(%r, 'utf8'), vm.createContext(w));
console.log(JSON.stringify(Object.keys(w.Backend._postPayload('u', 'n', false, 'c', 't', 'b', 'm', 'h', 1))));
console.log(JSON.stringify(Object.keys(w.Backend._replyPayload('u', 'n', false, 'b', 'h', 1))));
""" % os.path.join(WEB_DIR, "backend.js")
        r = subprocess.run([node, "-e", src], capture_output=True, text=True)
        post_keys, reply_keys = [set(json.loads(l)) for l in r.stdout.split()]
        rule_post = set(re.findall(r"'(\w+)'", re.search(r"keys\(\)\.hasOnly\(\[('uid', 'author', 'anon', 'circle'[^\]]*)\]\)", self.rules).group(1)))
        rule_reply = set(re.findall(r"'(\w+)'", re.search(r"keys\(\)\.hasOnly\(\[('uid', 'author', 'anon', 'body'[^\]]*)\]\)", self.rules).group(1)))
        self.assertLessEqual(post_keys, rule_post)
        self.assertLessEqual(reply_keys, rule_reply)

    # ---- 2. honest wording
    BANNED = ("women-only", "Women-only", "Verified mom", "verified by phone or Google", "Any verified mom",
              "Still women-only", "keeps out fake profiles", "Google account verified", "Verified with Google",
              "stays a women-only space")

    def test_no_women_only_or_verified_member_claims(self):
        with open(self.privacy_path, encoding="utf-8") as f:
            static = f.read()
        for name, src in (("app.js", self.app), ("data.js", self.data), ("index.html", self.index), ("privacy/index.html", static)):
            # The code comment explaining the rule may quote the old claims.
            code = re.sub(r"//[^\n]*", "", src)
            for bad in self.BANNED:
                self.assertNotIn(bad, code, "%s still claims %r" % (name, bad))

    def test_rendered_welcome_and_verify_copy_is_honest(self):
        self._node_run(r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
function ok(c, m) { if (!c) throw new Error(m); }
for (const real of [true, false]) {
  const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
  const w = { location: { hash: '#welcome', search: '', hostname: 'localhost' }, localStorage: ls,
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: { isReal: real }, console, setTimeout, clearTimeout };
  w.window = w; vm.runInContext(fs.readFileSync(path.join(webDir, 'data.js'), 'utf8'), vm.createContext(w));
  vm.runInContext(fs.readFileSync(path.join(webDir, 'app.js'), 'utf8'), w);
  const h = w.AANGAN.V.welcome().html + w.AANGAN.V['onboard/verify']().html + w.AANGAN.V.me().html;
  ok(!/verified mom|women-only|every member is verified/i.test(h), 'overclaim rendered: ' + h);
  ok(h.includes('A space for moms') && h.includes('moderated community') && h.includes('For moms · Kind · Moderated'), 'honest welcome copy missing');
  ok(h.includes('Signed in with'), 'Me shows sign-in method, not "verified"');
}
console.log('OK');
""" % WEB_DIR)

    # ---- 3. no fictional people in real mode
    def test_real_mode_shows_no_data_js_people_events_or_chats(self):
        self._node_run(r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
function ok(c, m) { if (!c) throw new Error(m); }
function boot(real, seed) {
  const ls = { store: {}, getItem(k) { return this.store[k] || null; }, setItem(k, v) { this.store[k] = v; }, removeItem(k) { delete this.store[k]; } };
  ls.store['aangan.demo.v1'] = JSON.stringify(seed);
  const w = { location: { hash: '#home', search: '', hostname: 'localhost' }, localStorage: ls,
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    Backend: { isReal: real, user: real ? { uid: 'u1' } : null }, console, setTimeout, clearTimeout };
  w.window = w; vm.runInContext(fs.readFileSync(path.join(webDir, 'data.js'), 'utf8'), vm.createContext(w));
  vm.runInContext(fs.readFileSync(path.join(webDir, 'app.js'), 'utf8'), w);
  return w;
}
const seedOn = { onboarded: true, city: 'Pune', nearbyOn: true };
const seedOff = { onboarded: true, city: 'Pune', nearbyOn: false };
const w = boot(true, seedOn), D = w.AANGAN_DATA;
const people = D.moms.map(m => m.nickname), events = D.events.map(e => e.title);
ok(people.length > 0 && events.length > 0, 'fixture sanity');
const pages = {
  chats: w.AANGAN.V.chats().html,
  nearbyOn: w.AANGAN.V.nearby().html,
  nearbyOff: boot(true, seedOff).AANGAN.V.nearby().html,
  meetups: w.AANGAN.V.meetups().html,
  me: w.AANGAN.V.me().html,
};
D.moms.forEach(m => { pages['chat/' + m.id] = w.AANGAN.V.chat(m.id).html; });
for (const [k, h] of Object.entries(pages)) {
  for (const n of people.concat(events)) ok(!h.includes(n), 'real ' + k + ' shows demo "' + n + '"');
  ok(!h.includes('data-act="say-hi"') && !h.includes('data-act="rsvp"') && !h.includes('chat-send') && !h.includes('map-card'), 'real ' + k + ' has demo controls');
}
ok(pages.chats.includes('Messages are coming soon') && pages['chat/' + D.moms[0].id].includes('Messages are coming soon'), 'chats coming soon: ' + pages.chats);
ok(pages.nearbyOn.includes('coming soon') && pages.nearbyOff.includes('coming soon') && !pages.nearbyOff.includes('nearby-toggle'), 'nearby coming soon');
ok(pages.meetups.includes('coming soon') && !pages.meetups.includes('data-act="soon"'), 'meetups coming soon');
const home = w.AANGAN.V.home().html;
D.circles.forEach(c => ok(!home.includes(c.members + ' moms'), 'real home shows fictional member count ' + c.members));
ok(!pages.me.includes('Who can message me') && !pages.me.includes('Hugs given') && !pages.me.includes('id="set-nearby"'), 'real Me has demo-only settings/stats');
// Demo mode keeps samples, clearly labelled.
const d = boot(false, seedOn);
const dc = d.AANGAN.V.chats().html;
ok(people.some(n => dc.includes(n)) && dc.includes('Sample chats with fictional moms (demo)'), 'demo chats labelled: ' + dc);
ok(d.AANGAN.V.meetups().html.includes('sample data (demo)'), 'demo meetups labelled');
console.log('OK');
""" % WEB_DIR)

    # ---- 4. static privacy page
    def test_static_privacy_page_exists_parses_and_is_in_sync(self):
        self.assertTrue(os.path.exists(self.privacy_path), "privacy/index.html missing (/privacy would 404)")
        with open(self.privacy_path, encoding="utf-8") as f:
            static = f.read()
        p = _Collector()
        p.feed(static)
        self.assertEqual(p.errors, [])
        self.assertEqual(p.stack, [])
        self.assertEqual(p.scripts, [], "static privacy page must work without JS")
        self.assertNotIn("@", static)
        self.assertNotIn("mailto:", static.lower())
        self.assertIn('href="../#home"', static)
        self.assertIn('href="../#safety"', static)
        # Every section title and key line of the in-app page is on the static page.
        app_date = re.search(r'var PRIVACY_UPDATED = "([^"]+)";', self.app).group(1)
        self.assertIn("Last updated: " + app_date, static)
        titles = re.findall(r'privacySection\("[^"]+", "([^"]+)"', self.app)
        self.assertGreaterEqual(len(titles), 9)
        for t in titles:
            self.assertIn(t, static)
        # app.js writes curly quotes/dashes as \uXXXX escapes inside JS strings.
        app_text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), self.app)
        for line in ("Only MomSakhi moderators can see it", "the post itself carries no account ID",
                     "we don\u2019t check identity or gender", "moderated community", "within 30 days",
                     "never sell your data", "18 and over"):
            self.assertTrue(line in static, "static page missing: " + line)
            self.assertTrue(line.replace("MomSakhi", '" + name + "') in app_text, "#privacy missing: " + line)

    def test_privacy_never_overclaims_anonymity(self):
        i = self.app.index("V.privacy = function")
        body = self.app[i:self.app.index("V.me = function")]
        self.assertIn("moderators can see it", body)
        for bad in ("no one can see", "No one can see", "completely anonymous", "fully anonymous", "untraceable"):
            self.assertNotIn(bad, body)

    def test_sw_precaches_privacy_page(self):
        shell = re.search(r"var SHELL = \[(.*?)\];", self.sw, re.S).group(1)
        self.assertIn('"privacy/"', shell)
        self.assertNotIn("a1b2c3d", self.sw + self.index, "placeholder cache version still in place")


class TestInviteCodes(unittest.TestCase):
    """2026-10-12 closed beta: invite codes.
    /invites/{code} {maxUses, uses, createdBy, createdAt, expiresAt?, note?} and
    /members/{uid} {code, joinedAt}; redemption is ONE batch (member doc + uses +1),
    and posts/replies/reactions/reports/profiles/postAuthors-create need isMember().
    Live proof against the emulator: ~/liquid/state/scratch/aangan_e2e/invite_e2e.py."""

    @classmethod
    def setUpClass(cls):
        cls.app = _read("app.js")
        cls.backend = _read("backend.js")
        with open(os.path.join(APP_DIR, "firestore.rules"), encoding="utf-8") as f:
            cls.rules = f.read()
        with open(os.path.join(APP_DIR, "privacy", "index.html"), encoding="utf-8") as f:
            cls.static_privacy = f.read()

    def _node_run(self, body):
        node = _node()
        if not node:
            self.skipTest("node not installed")
        harness = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const webDir = %r;
function ok(c, m) { if (!c) throw new Error(m); }
// Boots data.js + app.js in a fake window. Returns {w, ls, replaced}.
function boot(opts) {
  const ls = opts.ls || { store: {}, getItem(k) { return k in this.store ? this.store[k] : null; }, setItem(k, v) { this.store[k] = String(v); }, removeItem(k) { delete this.store[k]; } };
  if (opts.seed) ls.store['aangan.demo.v1'] = JSON.stringify(opts.seed);
  const replaced = [];
  const w = { location: { hash: opts.hash || '', search: opts.search || '', pathname: '/', hostname: 'localhost' }, localStorage: ls,
    history: { replaceState(a, b, url) { replaced.push(url); } },
    document: { addEventListener() {}, querySelector() { return null; }, getElementById() { return null; }, body: { setAttribute() {} } },
    navigator: opts.share ? { share() { return Promise.resolve(); } } : {},
    crypto: require('crypto').webcrypto,
    Backend: { isReal: !!opts.real, user: opts.user || null }, console, setTimeout, clearTimeout };
  w.window = w; vm.runInContext(fs.readFileSync(path.join(webDir, 'data.js'), 'utf8'), vm.createContext(w));
  vm.runInContext(fs.readFileSync(path.join(webDir, 'app.js'), 'utf8'), w);
  return { w, ls, replaced };
}
""" % WEB_DIR + body + "\nconsole.log('OK');\n"
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)

    # ---- code format
    def test_code_format_and_forgiving_input(self):
        self._node_run(r"""
const A = boot({}).w.AANGAN;
const seen = new Set();
for (let i = 0; i < 400; i++) {
  const c = A.newInviteCode();
  ok(/^SAKHI-[A-HJ-NP-Z2-9]{6}$/.test(c), 'bad code ' + c);
  ok(!/[01OI]/.test(c.slice(6)), 'ambiguous char in ' + c);
  seen.add(c);
}
ok(seen.size > 390, 'codes not random enough: ' + seen.size);
const N = A.normalizeInviteCode;
ok(N('sakhi-7f3kq9') === 'SAKHI-7F3KQ9', 'lowercase');
ok(N('  7F3K Q9 ') === 'SAKHI-7F3KQ9', 'no prefix + spaces');
ok(N('SAKHI7F3KQ9') === 'SAKHI-7F3KQ9', 'no dash');
ok(N('SAKHI-7F3K') === '', 'too short accepted');
ok(N('SAKHI-0O1I23') === '', '0/O/1/I accepted');
ok(N('') === '' && N(null) === '' && N('SAKHI-7F3KQ9/../x') === '', 'junk accepted');
""")
        # The app's regex and the rules' regex are the same alphabet.
        self.assertIn("var INVITE_RE = /^SAKHI-[A-HJ-NP-Z2-9]{6}$/;", self.app)
        self.assertIn("code.matches('^SAKHI-[A-HJ-NP-Z2-9]{6}$')", self.rules)
        self.assertIn('var INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";', self.app)
        self.assertIn("crypto", self.app[self.app.index("function newInviteCode()"):self.app.index("function normalizeInviteCode(")])

    # ---- ?invite= link: captured, stripped from the URL, kept through sign-in
    def test_invite_link_prefill_survives_redirect_sign_in(self):
        self._node_run(r"""
const X = boot({}).w.AANGAN.extractInvite;
let x = X('?emu=1&invite=sakhi-7f3kq9', '#welcome');
ok(x.code === 'SAKHI-7F3KQ9' && x.search === '?emu=1' && x.hash === '#welcome', 'search: ' + JSON.stringify(x));
x = X('', '#home?invite=SAKHI-7F3KQ9');
ok(x.code === 'SAKHI-7F3KQ9' && x.search === '' && x.hash === '#home', 'hash: ' + JSON.stringify(x));
x = X('', '#?invite=SAKHI-7F3KQ9&a=1');
ok(x.code === 'SAKHI-7F3KQ9' && x.hash === '#?a=1', 'bare hash: ' + JSON.stringify(x));
x = X('?a=1', '#q/abc');
ok(x.raw === null && x.code === '' && x.search === '?a=1' && x.hash === '#q/abc', 'no invite: ' + JSON.stringify(x));
x = X('?invite=hello', '');
ok(x.raw === 'hello' && x.code === '', 'malformed kept raw: ' + JSON.stringify(x));

// 1. Signed out, arrives from the link: stored + URL cleaned + welcome tells her.
const first = boot({ real: true, search: '?emu=1&invite=sakhi-7f3kq9', hash: '#welcome' });
ok(first.ls.store['momsakhi.invite'] === 'SAKHI-7F3KQ9', 'not stored: ' + JSON.stringify(first.ls.store));
ok(first.replaced.length === 1 && first.replaced[0] === '/?emu=1#welcome', 'URL not cleaned: ' + first.replaced);
const wel = first.w.AANGAN.V.welcome().html;
ok(wel.includes('id="welcome-invite"') && wel.includes('SAKHI-7F3KQ9'), 'welcome banner: ' + wel);
// 2. Google redirect round trip: the page reloads WITHOUT the param, same localStorage.
const back = boot({ real: true, ls: first.ls, hash: '', user: { uid: 'u1', email: 'mom@example.com' } });
ok(back.replaced.length === 0, 'nothing to strip on return');
ok(back.w.AANGAN.pendingInvite() === 'SAKHI-7F3KQ9', 'lost through redirect');
const a = back.w.AANGAN._access(); a.uid = 'u1'; a.status = 'none';
const inv = back.w.AANGAN.V.invite().html;
ok(inv.includes('id="invite-code"') && inv.includes('value="SAKHI-7F3KQ9"'), 'not prefilled: ' + inv);
ok(first.ls.store['momsakhi.invite.src'] === 'link' && inv.includes('id="invite-from-link"'), 'link source lost through redirect: ' + inv);
ok(!inv.includes('id="invite-submit" disabled'), 'Join disabled with a prefilled code');
// Demo mode: no banner even with a pending code.
ok(!boot({ ls: first.ls }).w.AANGAN.V.welcome().html.includes('welcome-invite'), 'demo shows invite banner');
""")
        # Auto-submit once after sign-in, and only for a non-member.
        body = self.app[self.app.index("function autoRedeem()"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("access.autoTried = true;", body)
        self.assertIn('access.status !== "none"', body)
        self.assertIn("autoRedeem(); return;", self.app)

    # ---- gate in real mode
    def test_gate_only_in_real_mode_for_signed_in_non_members(self):
        self._node_run(r"""
const u = { uid: 'u1', email: 'mom@example.com' };
// Demo: never gated.
ok(boot({ user: u }).w.AANGAN.gateOn() === false, 'demo gated');
// Real, signed out: welcome, not the gate.
ok(boot({ real: true }).w.AANGAN.gateOn() === false, 'signed-out gated');
// Real, signed in, unchecked, not cached: gated, with a "checking" screen.
let b = boot({ real: true, user: u }), A = b.w.AANGAN;
ok(A.gateOn() === true, 'unchecked non-member not gated');
ok(A.V.invite().html.includes('id="invite-checking"'), 'no checking state');
const acc = A._access(); acc.uid = 'u1'; acc.status = 'none';
ok(A.gateOn() === true, 'non-member not gated');
acc.error = A.INVITE_ERR.used;
let h = A.V.invite().html;
ok(h.includes('id="invite-error"') && h.includes('already been used up'), 'error state: ' + h);
ok(h.includes('data-act="feedback"') && h.includes('data-act="sign-out"') && h.includes('href="#privacy"'), 'gate exits: ' + h);
ok(h.includes('invite-only during the beta') && h.includes('isn\u2019t a check of who you are'), 'gate copy: ' + h);
acc.status = 'member';
ok(A.gateOn() === false, 'member gated');
// A known member (cached uid) never sees a gate flash while the check runs.
b = boot({ real: true, user: u, seed: { onboarded: true, memberUid: 'u1' } });
ok(b.w.AANGAN.gateOn() === false, 'cached member gated');
// ...but the cache is per uid.
ok(boot({ real: true, user: { uid: 'u2' }, seed: { memberUid: 'u1' } }).w.AANGAN.gateOn() === true, 'cache leaked to another uid');
// Error messages exist for every case.
for (const k of ['format', 'missing', 'used', 'expired']) ok(A.INVITE_ERR[k] && A.INVITE_ERR[k].length > 20, 'no error text for ' + k);
const S = A.inviteStatus, now = 1e12;
ok(S(null, now) === 'missing' && S({ uses: 1, maxUses: 1 }, now) === 'used' && S({ uses: 0, maxUses: 1, expiresAtMs: now - 1 }, now) === 'expired' &&
   S({ uses: 0, maxUses: 2, expiresAtMs: now + 1000 }, now) === 'ok' && S({ uses: 0, maxUses: 1, expiresAtMs: null }, now) === 'ok', 'inviteStatus');
""")
        render = self.app[self.app.index("function render(keepScroll)"):]
        render = render[:render.index("\n  }\n")]
        self.assertIn('var GATE_OPEN = ["invite", "privacy", "safety"];', self.app)
        self.assertIn('if (gated && GATE_OPEN.indexOf(r.name) < 0) r = { name: "invite", arg: null };', render)
        self.assertIn("if (gated) tabbar.hidden = true;", render)
        # Listeners and the profile read wait for membership.
        self.assertIn('if (r.name !== "q" || !r.arg || !B.user || !hasAccess()) return;', self.app)
        self.assertIn("if (!B.user || !B.listenMyReactions || !hasAccess()) return;", self.app)
        auth = self.app[self.app.index("window.Backend.onAuth(function(u) {"):]
        auth = auth[:auth.index("\n          });")]
        self.assertLess(auth.index("accessFor(u).then"), auth.index("getProfile(u.uid)"))
        sign_in = self.app[self.app.index("function afterGoogleSignIn(u)"):self.app.index("function routeByProfile(u)")]
        self.assertIn('if (!ok) { go("#invite"); return; }', sign_in)
        self.assertNotIn("getProfile", sign_in)

    # ---- moderator UI
    def test_moderator_invite_codes_section(self):
        self._node_run(r"""
const now = Date.now();
const b = boot({ real: true, user: { uid: 'm1' }, share: true }), A = b.w.AANGAN;
ok(A.V.mod().html.includes('Moderators only') && !A.V.mod().html.includes('Invite codes'), 'non-mod sees invites');
A._modState.isMod = true;
A._modState.invites = [
  { code: 'SAKHI-7F3KQ9', maxUses: 3, uses: 1, note: 'for Priya', expiresAtMs: null },
  { code: 'SAKHI-ABCDEF', maxUses: 1, uses: 1, note: null, expiresAtMs: null },
  { code: 'SAKHI-GHJKMN', maxUses: 5, uses: 0, note: '<b>x</b>', expiresAtMs: now - 1000 }];
const h = A.V.mod().html;
for (const s of ['Invite codes', 'id="invite-form"', 'id="inv-max"', 'max="50"', 'value="1"', 'id="inv-note"', 'id="inv-exp"', 'type="date"',
                 'id="inv-create"', 'data-act="invite-create"', '1 / 3 used', 'for Priya', 'Active', 'No seats left', 'Expired',
                 'data-act="invite-copy" data-code="SAKHI-7F3KQ9"', 'Copy invite link', 'data-act="invite-share"', 'data-act="invite-delete"'])
  ok(h.includes(s), 'mod invites missing ' + s + ': ' + h);
ok(!h.includes('<b>x</b>') && h.includes('&lt;b&gt;x&lt;/b&gt;'), 'note not escaped');
ok((h.match(/data-act="invite-disable"/g) || []).length === 1 && h.includes('data-act="invite-disable" data-code="SAKHI-7F3KQ9" data-uses="1"'), 'disable only on active');
ok(A.inviteLink('SAKHI-7F3KQ9') === 'https://sweta1910.github.io/momsakhi/?invite=SAKHI-7F3KQ9', 'link: ' + A.inviteLink('SAKHI-7F3KQ9'));
// No navigator.share -> no Share button.
const c = boot({ real: true, user: { uid: 'm1' } }).w.AANGAN; c._modState.isMod = true; c._modState.invites = A._modState.invites;
ok(!c.V.mod().html.includes('data-act="invite-share"'), 'share without navigator.share');
// Demo mode: no invite section.
ok(!boot({}).w.AANGAN.V.mod().html.includes('Invite codes'), 'demo shows invites');
""")
        create = self.app[self.app.index("function createInviteFromForm(btn)"):self.app.index("function copyInvite(code)")]
        self.assertIn("!modState.isMod", create)
        self.assertIn("n >= 1 && n <= INVITE_MAX_SEATS", create)
        self.assertIn('failToast("create the code", btn)', create)
        self.assertIn('var INVITE_LINK = "https://sweta1910.github.io/momsakhi/?invite=";', self.app)

    # ---- backend
    def test_backend_redeem_is_one_batch(self):
        i = self.backend.index("Backend.redeemInvite = function")
        body = self.backend[i:self.backend.index("\n      };", i)]
        self.assertIn('batch.set(doc(db, "members", uid), { code: code, joinedAt: serverTimestamp() });', body)
        self.assertIn('batch.update(doc(db, "invites", code), { uses: increment(1) });', body)
        self.assertEqual(body.count("batch.commit()"), 1)
        i = self.backend.index("Backend.createInvite = function")
        body = self.backend[i:self.backend.index("\n      };", i)]
        self.assertIn("{ maxUses: maxUses, uses: 0, createdBy: uid, createdAt: serverTimestamp() }", body)
        self.assertIn('setDoc(doc(db, "invites", code), data)', body)
        self.assertNotIn("merge", body)  # a collision must fail, never overwrite a live code
        self.assertIn('getDoc(doc(db, "members", uid))', self.backend)
        self.assertIn('getDoc(doc(db, "invites", code))', self.backend)

    # ---- rules
    def _block(self, header):
        i = self.rules.index(header)
        return self.rules[i:self.rules.index("\n    }", i)]

    def test_rules_invites_members_and_gate(self):
        r = self.rules
        inv = self._block("match /invites/{code}")
        self.assertIn("allow get: if request.auth != null;", inv)
        self.assertIn("allow list: if isModerator();", inv)
        self.assertIn("allow create: if isModerator() && validNewInvite(code);", inv)
        self.assertIn("redeemBump(code)", inv)
        self.assertIn("allow delete: if isModerator();", inv)
        self.assertNotIn("allow read", inv)   # `read` would include list
        self.assertNotIn("allow write", inv)
        mem = self._block("match /members/{uid}")
        self.assertIn("redeemedWith(request.resource.data.code)", mem)
        self.assertIn("request.resource.data.keys().hasOnly(['code', 'joinedAt'])", mem)
        self.assertIn("request.resource.data.joinedAt == request.time", mem)
        self.assertNotIn("update", mem)
        self.assertNotIn("allow list", mem)
        self.assertNotIn("allow read", mem)
        bump = r[r.index("function redeemBump(code)"):r.index("function validNewInvite(code)")]
        for s in ("affectedKeys().hasOnly(['uses'])", "request.resource.data.uses == resource.data.uses + 1",
                  "inviteOpen(resource.data)", "!exists(m) && existsAfter(m) && getAfter(m).data.code == code"):
            self.assertIn(s, bump)
        red = r[r.index("function redeemedWith(code)"):r.index("function redeemBump(code)")]
        self.assertIn("getAfter(inv).data.uses == get(inv).data.uses + 1", red)
        self.assertIn("inviteOpen(get(inv).data)", red)
        opn = r[r.index("function inviteOpen(d)"):r.index("function redeemedWith(code)")]
        self.assertIn("d.uses < d.maxUses", opn)
        self.assertIn("request.time < d.expiresAt", opn)
        new = r[r.index("function validNewInvite(code)"):r.index("// ---- Reactions")]
        for s in ("d.maxUses >= 1 && d.maxUses <= 50", "d.uses == 0", "d.createdBy == request.auth.uid", "d.note.size() <= 80"):
            self.assertIn(s, new)
        self.assertIn("(exists(/databases/$(database)/documents/members/$(request.auth.uid)) || isModerator())", r)
        # The gate: posts + replies read/create/update/delete, reactions, reports, profiles, postAuthors-create.
        posts = r[r.index("match /posts/{postId}"):r.index("match /postAuthors/{postId}")]
        self.assertEqual(posts.count("allow read: if isMember();"), 2)
        self.assertEqual(posts.count("allow create: if isMember() &&"), 2)
        self.assertIn("allow update: if isMember() && ((", posts)
        self.assertEqual(posts.count("allow delete: if isMember() &&"), 2)
        self.assertNotIn("allow read: if request.auth != null;", posts)
        self.assertEqual(r.count("allow create: if isMember() && authorRecordOk("), 2)
        self.assertIn("allow create: if isMember() &&\n                    request.resource.data.reporterUid", r)
        marks = self._block("match /userReactions/{uid}/marks/{markId}")
        self.assertEqual(marks.count("isMember()"), 3)
        # Feedback stays open to any signed-in mom; /moderators self-check stays open.
        self.assertNotIn("isMember()", self._block("match /feedback/{feedbackId}"))
        self.assertNotIn("isMember()", self._block("match /moderators/{uid}"))

    # ---- copy
    def test_welcome_and_privacy_say_invite_only_without_overclaiming(self):
        self._node_run(r"""
const real = boot({ real: true }).w.AANGAN, demo = boot({}).w.AANGAN;
ok(real.V.welcome().html.includes('Invite-only during the beta'), 'real welcome');
ok(!demo.V.welcome().html.includes('Invite-only'), 'demo welcome claims invite-only');
const p = real.V.privacy().html;
ok(p.includes('<b>invite-only</b>') && p.includes('isn\u2019t a check of who you are') && p.includes('which code you used and when you joined'), 'privacy: ' + p);
ok(!/verif(y|ied) (your|her) identity|verified mom/i.test(p), 'overclaim');
""")
        app_text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), self.app)
        for line in ("is <b>invite-only</b>: you join with an invite code or link from a moderator",
                     "An invite code only lets you in \u2014 it isn\u2019t a check of who you are.",
                     "we also note <b>which code you used and when you joined</b>"):
            self.assertIn(line, self.static_privacy, "static privacy missing: " + line)
            self.assertIn(line, app_text, "#privacy missing: " + line)
