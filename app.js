/* MomSakhi prototype — single-file SPA, zero backend.
 *
 * Why this shape: the prototype must open from `python3 -m http.server` (or even
 * file://) with no build step, so it is plain ES2017 in one IIFE. Views are pure
 * functions of (route, store) that return HTML strings; a single delegated click
 * handler on #app dispatches `data-act` attributes. Hash routes (#home, #q/p1,
 * #chat/m1 ...) make every screen deep-linkable, which is also what the
 * screenshot script relies on.
 *
 * State: immutable mock content lives in data.js (window.AANGAN_DATA). Anything
 * the visitor does (posts, reactions, RSVPs, hi-requests, chats, privacy
 * settings) is kept in `store` and persisted to localStorage so a demo survives
 * a refresh. "Reset demo" on the Me tab clears it.
 *
 * Real mode (Firebase, see backend.js): posts, replies and reactions live in
 * Firestore and every signed-in mom sees them live. Reaction counts are shared
 * counters on each post/reply; her own pressed state is her Firestore markers.
 */
(function () {
  "use strict";

  var D = window.AANGAN_DATA;
  var BRAND = D.brand; // single rename point: change brand.name in data.js
  var STORE_KEY = "aangan.demo.v1";

  // ---------------------------------------------------------------- store
  function freshStore() {
    return {
      onboarded: false,
      // Free-text city, optional ("" = not set). Only the meetup features (Meetups
      // tab + Nearby moms) need it; everything else works without. See cityGate().
      city: "",
      profile: { nickname: D.me.nickname, fullName: "", email: "", anonDefault: true, stages: ["Toddler"], langs: ["English", "Hindi"] },
      verify: { phone: false, google: false },
      authMethod: null,
      nearbyOn: false,
      msgPolicy: "mutual",
      posts: [],          // posts created in this demo session
      answers: {},        // postId -> [answers created in this demo]
      reacted: {},        // DEMO mode: "p1:hug" | "p1/a2:helpful" -> true
      // REAL mode: optimistic cache of HER Firestore markers (same key shape), so
      // pressed state paints before listenMyReactions answers. Firestore wins.
      reactedLive: {},
      reactedLiveUid: null,
      rsvp: {},           // eventId -> true
      req: {},            // momId -> "pending" | "accepted"
      chats: {},          // momId -> [messages]
      hidden: [],         // post ids hidden by this user
      reports: [],        // demo-mode reports (real mode reads Firestore /reports)
      blocked: [],        // author nicknames / mom ids blocked
      joined: {}          // circleId -> true
    };
  }
  // City is whatever the mom types (any city, town or area worldwide -- India or
  // abroad, ideally "City, Country"), so it is only
  // normalised, never matched against a list: control chars dropped, whitespace
  // collapsed, trimmed, capped at CITY_MAX. It is ALWAYS esc()'d when rendered.
  var CITY_MAX = 40;
  function cleanCity(v) {
    return String(v == null ? "" : v).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, CITY_MAX).trim();
  }
  function load() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        var s = Object.assign(freshStore(), JSON.parse(raw));
        // Before 2026-10-09 city was a picker id ("mv-sv"); an id is not a city
        // name, so old stores start with no city rather than a fake one.
        s.city = (typeof s.city === "string" && s.city !== "mv-sv") ? cleanCity(s.city) : "";
        delete s.waitlist;
        return s;
      }
    } catch (e) { /* private mode or bad JSON: start fresh */ }
    return freshStore();
  }
  var store = load();
  // Moderator state is deliberately NOT in `store`: it must never be persisted to
  // localStorage (a stale/forged flag would only hide buttons anyway -- Firestore
  // rules are the real gate). Reset on every auth change by syncModerator().
  var modState = { isMod: false, reports: [], unsub: null, postCache: {}, fetching: {}, feedback: [], unsubFb: null };
  function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch (e) { /* ignore */ } }

  // -------------------------------------------------------------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function initials(name) {
    var parts = String(name).replace(/([a-z])([A-Z])/g, "$1 $2").split(/[\s._-]+/).filter(Boolean);
    return ((parts[0] || "?")[0] + ((parts[1] || "")[0] || "")).toUpperCase();
  }
  function byId(list, id) { for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]; return null; }
  function circle(id) { return byId(D.circles, id); }
  function mom(id) { return byId(D.moms, id); }
  function hood(id) { return byId(D.neighbourhoods, id); }

  // ---------------------------------------------------------------- city
  // One city input used by onboarding, the meetups gate and the Me sheet. The
  // <datalist> only SUGGESTS common cities worldwide -- Indian metros plus
  // diaspora hubs written "City, Country" (data.js citySuggestions); any text is
  // accepted. Our moms are Indian moms anywhere in the world, and city names
  // repeat across countries (Hyderabad, Birmingham), so every city input carries
  // CITY_HINT nudging "City, Country" -- meetups match on this exact string.
  // Only one city input is on screen at a time, so the datalist id never collides.
  var CITY_HINT = "Outside India? Add the country too, e.g. “Birmingham, UK”, so you find the right meetups.";
  function hasCity() { return !!store.city; }
  function cityField(id, label, hint) {
    return '<div class="field city-field"><label for="' + id + '">' + label + "</label>" +
      '<input class="input" id="' + id + '" list="city-suggestions" maxlength="' + CITY_MAX + '" value="' + esc(store.city) + '" placeholder="e.g. Pune, San Jose, London" autocomplete="address-level2" enterkeyhint="done" data-city-input="1">' +
      '<datalist id="city-suggestions">' + (D.citySuggestions || []).map(function (c) { return '<option value="' + esc(c) + '">'; }).join("") + "</datalist>" +
      '<p class="hint">' + (hint ? hint + " " : "") + CITY_HINT + "</p></div>";
  }
  // Firestore keeps city on the mom's /profiles/{uid} doc (rules already let the
  // owner write her own doc). Locally it lives in store.city, NOT store.profile,
  // so these two map between the shapes in one place.
  function applyProfile(p) {
    if (!p) return;
    if (typeof p.city === "string") store.city = cleanCity(p.city);
    var rest = Object.assign({}, p); delete rest.city;
    store.profile = Object.assign(store.profile || {}, rest);
  }
  function profileDoc() { return Object.assign({}, store.profile, { city: store.city }); }
  // Saves locally always. In real mode it also writes Firestore, but only once
  // she has finished onboarding: a city-only profile doc written mid-onboarding
  // would make getProfile() treat her as onboarded on the next load.
  function saveCity(value, btn) {
    store.city = cleanCity(value); save();
    var B = window.Backend;
    if (isRealMode() && B.user && store.onboarded) {
      busy(btn);
      return B.saveProfile(B.user.uid, { city: store.city }).then(function () {
        if (btn) btn.disabled = false;
      }).catch(failToast("save your city", btn));
    }
  }
  // Firestore createdAt is null on a pending local write (serverTimestamp not yet
  // resolved); treat anything missing or odd as "just now" rather than throwing.
  function formatTime(t) {
    if (!t) return "just now";
    if (typeof t === "string") return t;
    if (typeof t === "number") { var ms = t; t = { toDate: function () { return new Date(ms); } }; }
    if (typeof t.toDate === "function") {
      var d = t.toDate();
      if (!d || isNaN(d.getTime())) return "just now";
      var diff = (Date.now() - d.getTime()) / 60000;
      if (diff < 1) return "just now";
      if (diff < 60) return Math.floor(diff) + "m";
      if (diff < 1440) return Math.floor(diff/60) + "h";
      return Math.floor(diff/1440) + "d";
    }
    return "now";
  }

  function allPosts() {
    if (window.Backend && window.Backend.isReal) {
       return (window.Backend.posts || []).filter(function (p) {
         p.time = formatTime(p.createdAt);
         return store.hidden.indexOf(p.id) < 0 && !(p.author && store.blocked.indexOf(p.author) >= 0);
       });
    }
    return store.posts.concat(D.posts).filter(function (p) {
      return store.hidden.indexOf(p.id) < 0 && !(p.author && store.blocked.indexOf(p.author) >= 0);
    });
  }
  function post(id) {
    if (window.Backend && window.Backend.isReal) {
      var arr = window.Backend.posts || [];
      for (var i=0; i<arr.length; i++) if (arr[i].id === id) { arr[i].time = formatTime(arr[i].createdAt); return arr[i]; }
      return null;
    }
    return byId(store.posts.concat(D.posts), id);
  }
  function answersFor(p) {
    if (window.Backend && window.Backend.isReal) {
      var list = window.Backend._currentReplies || [];
      list.forEach(function(a) { a.time = formatTime(a.createdAt); });
      return list.filter(function (a) { return !(a.author && store.blocked.indexOf(a.author) >= 0); });
    }
    var list = (p.answers || []).concat(store.answers[p.id] || []);
    return list.filter(function (a) { return !(a.author && store.blocked.indexOf(a.author) >= 0); });
  }
  function momStatus(m) { return store.req[m.id] || m.status; }

  var ICONS = {
    home: '<path d="M3.5 10.5 12 3.5l8.5 7V19a1.5 1.5 0 0 1-1.5 1.5h-4.5V15h-5v5.5H5A1.5 1.5 0 0 1 3.5 19z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1.4-3.6 4.3-5.5 7.5-5.5s6.1 1.9 7.5 5.5"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    more: '<circle cx="5.5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
    send: '<path d="M4.5 12 20 4.5 14 20l-2.8-6.2z"/><path d="m11.2 13.8 3.3-3.3"/>',
    chat: '<path d="M20.5 12a8.5 8.5 0 0 1-12.3 7.6L3.5 20.5l1-4.4A8.5 8.5 0 1 1 20.5 12z"/>',
    shield: '<path d="M12 3 4.5 6v5.5c0 4.7 3.2 8.3 7.5 9.5 4.3-1.2 7.5-4.8 7.5-9.5V6z"/><path d="m9 12 2 2 4-4"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    flag: '<path d="M5.5 21V4.5m0 0h11l-2.2 4 2.2 4h-11"/>',
    block: '<circle cx="12" cy="12" r="8.5"/><path d="m6 6 12 12"/>',
    eyeoff: '<path d="M3 3l18 18M10.6 6.1c.5-.1.9-.1 1.4-.1 5 0 8.5 4.5 9.5 6-.5.8-1.6 2.3-3.2 3.6M6.6 6.6C4.6 7.9 3.1 9.9 2.5 12c1 1.5 4.5 6 9.5 6 1.6 0 3-.4 4.3-1.1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    camera: '<path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2L9 5h6l1.5 2h2A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><circle cx="12" cy="13" r="3.5"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    users: '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 19.5c1-3 3.5-4.5 6.5-4.5s5.5 1.5 6.5 4.5"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18 15.2c1.7.6 2.9 2 3.5 4.3"/>',
    reset: '<path d="M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20"/>',
    hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11m0-1V4a1.5 1.5 0 0 1 3 0v7m0-5.5a1.5 1.5 0 0 1 3 0V12m0-3.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.6-2.2L5 15.5a1.6 1.6 0 0 1 2.4-2.1L8 14"/>'
  };
  function icon(name, cls) {
    return '<svg class="' + (cls || "") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }
  function logoMark(cls) {
    return '<svg class="logo-mark ' + (cls || "") + '" viewBox="0 0 64 64" aria-hidden="true">' +
      '<circle cx="32" cy="32" r="32" fill="#FCEFD3"/>' +
      '<path d="M32 13c6.5 7.5 8.5 15.5 0 28-8.5-12.5-6.5-20.5 0-28z" fill="#B9572F"/>' +
      '<path d="M13 25.5c9.5 0 16 5.5 19 15.5-10.5 1-17-4.5-19-15.5z" fill="#E8A33D"/>' +
      '<path d="M51 25.5c-9.5 0-16 5.5-19 15.5 10.5 1 17-4.5 19-15.5z" fill="#E8A33D"/>' +
      '<path d="M17 46c4.6 2.6 9.6 3.8 15 3.8S42.4 48.6 47 46" stroke="#1E4D4F" stroke-width="3.2" fill="none" stroke-linecap="round"/>' +
      "</svg>";
  }
  function googleIcon(size) {
    var sz = size || 18;
    return '<svg viewBox="0 0 24 24" width="' + sz + '" height="' + sz + '" class="google-icon" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>' +
      '<path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>' +
      '<path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05"/>' +
      '<path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335"/>' +
      '</svg>';
  }
  function mandala() {
    // Concentric petal rings, drawn at low opacity behind the welcome hero.
    var s = '<svg class="mandala" viewBox="-100 -100 200 200" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">';
    [[16, 78, 14], [12, 54, 11], [8, 32, 8]].forEach(function (ring) {
      for (var i = 0; i < ring[0]; i++) {
        var a = (360 / ring[0]) * i;
        s += '<ellipse cx="0" cy="-' + ring[1] + '" rx="' + (ring[2] * 0.55) + '" ry="' + ring[2] + '" transform="rotate(' + a + ')"/>';
      }
    });
    s += '<circle r="92"/><circle r="66"/><circle r="18"/><circle r="6" fill="currentColor"/></svg>';
    return s;
  }
  function avatar(name, hue, size) {
    if (!name) return '<span class="avatar hue-anon ' + (size || "") + '" aria-label="Anonymous mom">' + icon("user") + "</span>";
    return '<span class="avatar hue-' + (hue || "teal") + " " + (size || "") + '" aria-hidden="true">' + esc(initials(name)) + "</span>";
  }
  function switchEl(on, act, label, extra) {
    return '<button class="switch" role="switch" aria-checked="' + (on ? "true" : "false") + '" aria-label="' + esc(label) + '" data-act="' + act + '"' + (extra || "") + "></button>";
  }
  function greeting() {
    var h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }

  // ---------------------------------------------------------- kindness
  // Client-side demo only: a phrase list with softer alternatives. A real build
  // would use a moderation model server-side; this just shows the UX moment.
  function kindnessScan(text) {
    var lower = text.toLowerCase(), hits = [];
    D.kindness.phrases.forEach(function (p) {
      var re = new RegExp("\\b" + p.match.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i");
      if (re.test(lower) && !hits.some(function (h) { return h.match.indexOf(p.match) >= 0; })) hits.push(p);
    });
    return hits;
  }
  function softenText(text, hits) {
    var curated = (D.kindness.rewrites || []).filter(function (r) { return r.from.trim() === String(text).trim(); })[0];
    if (curated) return curated.to;
    var out = text;
    hits.forEach(function (h) {
      out = out.replace(new RegExp("\\b" + h.match.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi"), h.softer);
    });
    return out;
  }
  function highlight(text, hits, tag) {
    var out = esc(text);
    hits.forEach(function (h) {
      var src = tag === "ins" ? h.softer : h.match;
      out = out.replace(new RegExp("\\b(" + esc(src).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")\\b", "gi"), "<" + tag + ">$1</" + tag + ">");
    });
    return out;
  }
  function nudgeHtml(text, hits, scope) {
    var softened = softenText(text, hits);
    return '<div class="nudge" id="' + scope + '-nudge" role="alert">' +
      '<div class="nudge-head"><span class="ni">💛</span><b>Kindness check</b></div>' +
      "<p>This might land harder than you mean. Moms here are often having a tough day — " +
      "could you say it a little more gently?</p>" +
      '<p class="tiny" style="margin-top:8px">Words that may sting: ' + hits.map(function (h) { return "<mark>" + esc(h.match) + "</mark>"; }).join(" ") + "</p>" +
      '<div class="suggest"><span class="tiny">Suggested</span><br>' + highlight(softened, hits, "ins") + "</div>" +
      '<div class="nudge-actions">' +
      '<button class="btn btn-primary btn-sm" data-act="kind-use" data-scope="' + scope + '" id="' + scope + '-kind-use">Use kinder wording</button>' +
      '<button class="btn btn-ghost btn-sm" data-act="kind-edit" data-scope="' + scope + '">Edit myself</button>' +
      "</div>" +
      '<button class="skip" data-act="kind-skip" data-scope="' + scope + '">Post as is</button>' +
      "</div>";
  }

  // Client-side demo only: A real launch needs server-side moderation + trained human review.
  var WORRY_PHRASES = ["kill myself", "end my life", "want to die", "hurt myself", "hurt my baby", "better off without me", "can't go on", "no reason to live"];
  function worryingScan(text) {
    var lower = String(text).toLowerCase();
    for (var i = 0; i < WORRY_PHRASES.length; i++) {
      if (lower.indexOf(WORRY_PHRASES[i]) >= 0) return true;
    }
    return false;
  }

  function showSafetySheet(postCbAction) {
    var html = '<div style="padding:10px">' +
      '<div style="text-align:center;margin-bottom:16px"><span style="font-size:32px">🤍</span></div>' +
      '<h3 style="text-align:center;margin-bottom:8px">It sounds like you\'re carrying a lot right now. You deserve support right away.</h3>' +
      '<p class="tiny" style="text-align:center;margin-bottom:24px">National Maternal Mental Health Hotline: 1-833-852-6262<br>988 Suicide & Crisis Lifeline: 988</p>' +
      '<button class="btn btn-primary btn-block" data-act="sheet-close-then-safety" style="margin-bottom:12px">Talk to someone now</button>' +
      '<button class="btn btn-ghost btn-block" data-act="' + postCbAction + '">Post to the circle</button>' +
      '</div>';
    openSheet(html);
  }

  // ---------------------------------------------------------- components
  // Reactions. DEMO mode: counts are fictional data.js numbers + her local toggle.
  // REAL mode (2026-10-09, "other moms don't see my hug"): counts are the shared
  // reactions.{r} counters on the Firestore post/reply doc (they already include
  // her own reaction), and pressed state comes from her Firestore markers. See
  // Backend.setReaction and the reactions block in firestore.rules.
  var reactState = { mine: null, pending: {} }; // mine: markers from Firestore (null = not loaded yet); pending: key -> wanted state while a write is in flight
  function isReacted(k) {
    if (!isRealMode()) return !!store.reacted[k];
    if (reactState.pending[k] !== undefined) return reactState.pending[k];
    if (reactState.mine) return !!reactState.mine[k];
    var B = window.Backend;
    return !!(B.user && store.reactedLiveUid === B.user.uid && store.reactedLive[k]);
  }
  function reactCount(counts, r, on) {
    if (isRealMode()) return Math.max(0, +(counts || {})[r.id] || 0);
    return ((counts || {})[r.id] || 0) + (on ? 1 : 0);
  }
  function reactBtnInner(r, n) { return '<span class="e">' + r.emoji + "</span>" + r.label + (n ? " · " + n : ""); }
  function reactionBar(key, counts) {
    return D.reactions.map(function (r) {
      var on = isReacted(key + ":" + r.id);
      var n = reactCount(counts, r, on);
      return '<button class="react" data-act="react" data-key="' + key + '" data-r="' + r.id + '" aria-pressed="' + on + '" aria-label="' + r.label + " (" + n + ')">' +
        reactBtnInner(r, n) + "</button>";
    }).join("");
  }
  // Counts for a reaction-bar key: "<postId>" or "<postId>/<replyId>" (real mode).
  function liveCountsFor(key) {
    var i = key.indexOf("/");
    if (i < 0) { var p = post(key); return (p && p.reactions) || {}; }
    var rid = key.slice(i + 1), reps = window.Backend._currentReplies || [];
    for (var j = 0; j < reps.length; j++) if (reps[j].id === rid) return reps[j].reactions || {};
    return {};
  }
  // Minimal DOM patch: rewrites only reaction buttons whose state changed, so a
  // live update never re-renders the screen (open reply draft, focus and scroll
  // stay exactly as they were). Real mode only; demo buttons patch themselves.
  function patchReactions() {
    if (!isRealMode()) return;
    var screen = $("#screen"); if (!screen) return;
    var btns = screen.querySelectorAll(".react[data-key]");
    var byR = {}; D.reactions.forEach(function (r) { byR[r.id] = r; });
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i], key = b.getAttribute("data-key"), r = byR[b.getAttribute("data-r")];
      if (!r) continue;
      var on = isReacted(key + ":" + r.id), n = reactCount(liveCountsFor(key), r, on);
      var label = r.label + " (" + n + ")";
      if (b.getAttribute("aria-pressed") !== String(on)) b.setAttribute("aria-pressed", on);
      if (b.getAttribute("aria-label") !== label) { b.setAttribute("aria-label", label); b.innerHTML = reactBtnInner(r, n); }
    }
  }
  function postCard(p, opts) {
    opts = opts || {};
    // Firestore posts may have no reactions map yet and may name an unknown circle;
    // fall back instead of throwing, which would blank the whole feed.
    var c = p.circle ? circle(p.circle) : null;
    var name = p.anon ? "Anonymous mom" : (p.author || "Mom");
    var count = (window.Backend && window.Backend.isReal) ? (p.replyCount || 0) : answersFor(p).length;
    return '<article class="card post ' + (opts.full ? "" : "clickable") + '" ' + (opts.full ? "" : 'data-href="#q/' + p.id + '"') + ' id="post-' + p.id + '">' +
      '<div class="post-head">' + avatar(p.anon ? null : p.author, p.hue) +
      '<div class="who"><b>' + esc(name) + "</b><span>" + esc(p.meta) + " · " + esc(p.time) + "</span></div>" +
      (opts.full ? '<button class="icon-btn" data-act="post-menu" data-id="' + p.id + '" aria-label="More options">' + icon("more") + "</button>" : "") +
      "</div>" +
      (opts.full || !c ? "" : '<div class="post-tagrow"><a class="tag" style="text-decoration:none" href="#circle/' + c.id + '">' + c.emoji + " " + esc(c.name) + "</a></div>") +
      "<h3>" + esc(p.title) + "</h3>" +
      (p.body ? '<p class="body ' + (opts.full ? "" : "clamp") + '">' + esc(p.body) + "</p>" : "") +
      '<div class="post-foot">' + reactionBar(p.id, p.reactions || {}) +
      (opts.full ? "" : '<span class="replies-count">' + icon("chat") + count + "</span>") +
      "</div></article>";
  }
  function emptyState(emoji, title, text) {
    return '<div class="empty-answers"><div class="ea">' + emoji + '</div><b>' + title + '</b><p class="tiny" style="margin-top:4px">' + text + "</p></div>";
  }

  // ---------------------------------------------------------------- views
  var V = {};

  // ------------------------------------------- in-app browser (webview) card
  // Google refuses OAuth inside embedded webviews (403 disallowed_useragent), so
  // a mom who taps the link inside Instagram/Facebook/etc. could never sign in.
  // We warn ONLY on browsers with a reliable UA marker. WhatsApp's in-app
  // browser has no reliable marker, so it is deliberately NOT matched (a false
  // warning there would scare off the moms we invite by WhatsApp). Generic
  // Android WebView ("; wv)") is matched: Google blocks it too.
  // The same card also appears after a sign-in error that means "webview"
  // (signInBlocked), which covers in-app browsers we can't recognise.
  var IAB_RE = /FBAN|FBAV|FB_IAB|Instagram|LinkedInApp|Snapchat|musical_ly|TikTok|BytedanceWebview|Line\/|; wv\)/;
  var signInBlocked = false;
  function inAppBrowser(ua) {
    ua = ua || "";
    if (!IAB_RE.test(ua)) return null;
    var name = /Instagram/.test(ua) ? "Instagram"
      : /Messenger|MESSENGER/.test(ua) ? "Messenger"
      : /FBAN|FBAV|FB_IAB/.test(ua) ? "Facebook"
      : /LinkedInApp/.test(ua) ? "LinkedIn"
      : /Snapchat/.test(ua) ? "Snapchat"
      : /musical_ly|TikTok|BytedanceWebview/.test(ua) ? "TikTok"
      : /Line\//.test(ua) ? "LINE" : "";
    return { name: name, os: /Android/.test(ua) ? "android" : isIOS(ua) ? "ios" : "other" };
  }
  function isWebviewAuthError(e) {
    var code = (e && e.code) || "", msg = (e && e.message) || "";
    return ["auth/disallowed-useragent", "auth/web-storage-unsupported",
            "auth/operation-not-supported-in-this-environment"].indexOf(code) >= 0 ||
      /disallowed.useragent/i.test(msg);
  }
  // The page's own address (no #route), built from location so it is never
  // hardcoded: https://sweta1910.github.io/momsakhi/ on Pages, localhost locally.
  function appLink(loc) {
    return (loc.origin || (loc.protocol + "//" + loc.host)) + loc.pathname;
  }
  // Android: hand the page to Chrome. e.g.
  // intent://sweta1910.github.io/momsakhi/#Intent;scheme=https;package=com.android.chrome;end
  function chromeIntentUrl(loc) {
    return "intent://" + loc.host + loc.pathname + (loc.search || "") +
      "#Intent;scheme=" + String(loc.protocol || "https:").replace(":", "") + ";package=com.android.chrome;end";
  }
  function inAppCard() {
    var ua = nav().userAgent || "";
    var iab = inAppBrowser(ua);
    if (!iab && !signInBlocked) return "";
    var os = iab ? iab.os : (/Android/.test(ua) ? "android" : isIOS(ua) ? "ios" : "other");
    var where = iab && iab.name ? esc(iab.name) + "'s" : "this app's";
    var loc = window.location, link = appLink(loc);
    var step = os === "ios" ? "Tap <b>⋯</b> (top right), then <b>Open in Safari</b>."
      : os === "android" ? "Tap <b>Open in Chrome</b> below, or <b>⋮</b> then <b>Open in browser</b>."
      : "Copy the link and open it in Chrome or Safari.";
    return '<div class="card iab-card" id="iab-card" role="alert">' +
      "<b>To sign in, open " + esc(BRAND.name) + " in Chrome or Safari</b>" +
      "<span>Google doesn't allow sign-in inside " + where + " built-in browser.</span>" +
      '<span class="iab-step">' + step + "</span>" +
      '<input class="input iab-link" id="iab-link" readonly value="' + esc(link) + '" aria-label="' + esc(BRAND.name) + ' link">' +
      '<div class="iab-actions"><button class="btn btn-primary btn-sm" data-act="copy-app-link" id="iab-copy">Copy link</button>' +
      (os === "android" ? '<a class="btn btn-ghost btn-sm" id="iab-chrome" href="' + esc(chromeIntentUrl(loc)) + '">Open in Chrome</a>' : "") +
      "</div></div>";
  }
  function showSignInBlocked() {
    signInBlocked = true;
    if (parseHash().name !== "welcome") go("#welcome"); else render(true);
    var card = $("#iab-card"); if (card && card.scrollIntoView) card.scrollIntoView({ block: "center" });
  }

  V.welcome = function () {
    return { tab: null, html:
      '<div class="welcome view">' +
      '<div class="toran" aria-hidden="true"></div>' + mandala() +
      // First thing on screen: a mom arriving from Instagram must see it without scrolling.
      '<div class="welcome-hero">' + inAppCard() +
      '<div class="logo">' + logoMark() + '<span class="logo-word" style="font-size:28px">' + esc(BRAND.name) + "</span></div>" +
      "<h1>" + esc(BRAND.tagline).replace("sakhi", "<em>sakhi</em>") + "</h1>" +
      '<p class="sakhi-note"><b>Sakhi</b> (सखी) means a close friend — no judgement, just moms.</p>' +
      "<p>" + esc(BRAND.blurb) + "</p></div>" +
      '<div class="promise">' +
      promiseRow("🤍", "var(--plum-soft)", "Women-only & verified", "Every member is verified by phone or Google") +
      promiseRow("🫶", "var(--peach)", "Anonymous when you need it", "Ask anything without your name on it") +
      promiseRow("📍", "var(--teal-soft)", "Moms near you", "Meetups in your city · add it whenever you like") +
      "</div>" +
      '<div class="welcome-cta">' +
      '<div class="welcome-cta-header"><h3>Join the circle</h3><p>Women-only · Safe · Verified</p></div>' +
      '<button class="btn btn-google btn-block" data-act="google-signin" id="google-signin">' + googleIcon(18) + "<span>Continue with Google</span></button>" +
      '<div class="auth-divider"><span>or</span></div>' +
      '<button class="btn btn-primary btn-block" data-act="start-phone-onboard" id="get-started">Continue with phone</button>' +
      '<button class="btn btn-ghost btn-block" data-act="skip-onboarding" id="have-account">I already have an account</button>' +
      '<p class="tiny" style="margin-bottom:8px;font-weight:600">Moms supporting moms — not a replacement for your doctor or therapist.</p>' +
      '<p class="tiny terms-line" id="welcome-terms">By continuing you agree to our <a href="#privacy" id="welcome-privacy">Terms &amp; Privacy</a>.</p>' +
      '<p class="tiny">' + (isRealMode() ? "Real moms, real posts · sign in with Google to join" : "Prototype · all people, posts and places are fictional demo data") + '</p>' +
      "</div></div>" };
  };
  function promiseRow(emoji, bg, title, sub) {
    return '<div class="card promise-row"><span class="pi" style="background:' + bg + '">' + emoji + "</span><div><b>" + title + "</b><span>" + sub + "</span></div></div>";
  }
  function steps(n) {
    return '<div class="ob-steps" aria-label="Step ' + n + ' of 3">' + [1, 2, 3].map(function (i) { return "<i class=\"" + (i <= n ? "on" : "") + "\"></i>"; }).join("") + "</div>";
  }
  function obBack(to) {
    return '<div class="backbar"><button class="icon-btn" data-act="go" data-to="' + to + '" aria-label="Back">' + icon("back") + '</button><span class="title"></span></div>';
  }

  // Step 1 is optional: Continue works with an empty box and "Skip for now" clears
  // it. The city is only needed for meetups; cityGate() asks again there.
  V["onboard/city"] = function () {
    return { tab: null, html:
      '<div class="view">' + obBack("#welcome") + '<div class="ob">' + steps(1) +
      "<h1>Where are you, mama?</h1>" +
      '<p class="lead">Optional — you only need a city to join meetups and find moms nearby. You can add or change it anytime from Me.</p>' +
      cityField("city-input", 'Your city <span class="tiny">(optional)</span>', "Pick a suggestion or type your own city, town or area.") +
      '<div class="ob-foot"><button class="btn btn-primary btn-block" data-act="city-continue" id="city-continue">Continue</button>' +
      '<button class="btn btn-ghost btn-block" data-act="city-skip" id="city-skip" style="margin-top:8px">Skip for now</button></div>' +
      "</div></div>" };
  };

  V["onboard/about"] = function () {
    var p = store.profile;
    var stageChips = D.stages.map(function (s) {
      return '<button class="chip" data-act="toggle-stage" data-v="' + esc(s) + '" aria-pressed="' + (p.stages.indexOf(s) >= 0) + '">' + icon("check", "check") + esc(s) + "</button>";
    }).join("");
    var langChips = D.languages.map(function (l) {
      return '<button class="chip" data-act="toggle-lang" data-v="' + esc(l) + '" aria-pressed="' + (p.langs.indexOf(l) >= 0) + '">' + icon("check", "check") + esc(l) + "</button>";
    }).join("");
    return { tab: null, html:
      '<div class="view">' + obBack("#onboard/city") + '<div class="ob">' + steps(2) +
      "<h1>A little about you</h1>" +
      '<p class="lead">Only what you choose to share. You can change this anytime.</p>' +
      '<div class="field"><label for="nick">Pick a nickname</label>' +
      '<input class="input" id="nick" maxlength="20" value="' + esc(p.nickname) + '" autocomplete="off" data-input="nick">' +
      '<p class="hint">No need for your real name — most moms here don\'t use it.</p></div>' +
      '<div class="card toggle-row" style="margin-top:16px"><div class="grow"><b>Post anonymously by default</b><span>You can switch it per post</span></div>' + switchEl(p.anonDefault, "toggle-anon-default", "Post anonymously by default") + "</div>" +
      '<div class="field"><span class="label">Your kids\' stages</span><div class="chips">' + stageChips + "</div></div>" +
      '<div class="field"><span class="label">Languages you speak</span><div class="chips">' + langChips + "</div></div>" +
      '<div class="ob-foot"><button class="btn btn-primary btn-block" data-act="go" data-to="#onboard/verify" id="about-continue"' + (p.nickname.trim() ? "" : " disabled") + ">Continue</button></div>" +
      "</div></div>" };
  };

  V["onboard/verify"] = function () {
    var v = store.verify;
    var isGoogle = !!(v.google || store.authMethod === "google");
    var phoneState = v.phone ? '<span class="done-badge">' + icon("check") + "Phone verified</span>"
      : '<div class="phone-input"><input class="input cc" value="+1" aria-label="Country code" readonly><input class="input" value="(650) 555-0142" aria-label="Phone number" inputmode="tel"></div>' +
        '<button class="btn btn-ghost btn-sm" style="margin-top:10px" data-act="verify-phone" id="verify-phone">Send code</button>';

    var verifyCard;
    if (isGoogle) {
      verifyCard = '<div class="card verify-card"><span class="vi" style="background:#fff;border:1px solid #dadce0">' + googleIcon(22) + '</span><div class="grow"><b>Google account verified</b><span class="tiny">' + esc(store.profile.email || "priya.sharma@gmail.com") + '</span><div class="state"><span class="done-badge">' + icon("check") + "Verified with Google</span></div></div></div>";
    } else {
      verifyCard = '<div class="card verify-card"><span class="vi">' + icon("phone") + '</span><div class="grow"><b>Verify your phone</b><span class="tiny">One account per number — keeps out fake profiles.</span><div class="state">' + phoneState + "</div></div></div>" +
        (v.phone ? "" : '<div class="auth-divider" style="margin:14px 0 10px"><span>or</span></div>' +
          '<button class="btn btn-google btn-block btn-sm" data-act="google-signin" id="verify-google">' + googleIcon(16) + '<span>Verify with Google instead</span></button>');
    }

    var canEnter = isGoogle || v.phone;
    return { tab: null, html:
      '<div class="view">' + obBack("#onboard/about") + '<div class="ob">' + steps(3) +
      "<h1>Keeping it moms-only</h1>" +
      '<p class="lead">A quick, private check so this stays a women-only space.</p>' +
      verifyCard +
      '<div class="ob-foot"><button class="btn btn-primary btn-block" data-act="finish-onboarding" id="enter-app"' + (canEnter ? "" : " disabled") + ">Enter " + esc(BRAND.name) + "</button>" +
      (isRealMode() ? "" : '<p class="tiny" style="text-align:center;margin-top:10px">Demo: no real data is sent anywhere.</p>') + "</div>" +
      "</div></div>" };
  };

  function homeTop() {
    var sub = hasCity() ? '<div class="sub">' + icon("pin", "").replace('class=""', 'style="width:12px;height:12px"') + esc(store.city) + "</div>" : "";
    return '<header class="topbar"><div class="logo">' + logoMark() + '<div><div class="logo-word">' + esc(BRAND.name) + "</div>" + sub + "</div></div>" +
      '<span style="flex:1"></span>' +
      '<a href="#safety" class="icon-btn" aria-label="Need help now?" style="color:var(--plum)">' + icon("shield") + '</a>' +
      '<a class="icon-btn" href="#chats" aria-label="Messages" id="open-chats">' + icon("chat") + '<span class="dot"></span></a></header>';
  }

  // ------------------------------------------------ Add to Home Screen hint
  // Shown on Home only (never on the welcome screen: one ask at a time), at most
  // once per device: the first time we decide to show it we set INSTALL_KEY, and
  // keep showing it for the rest of that page session until she taps x / Add.
  // Android/desktop Chrome: only when the browser has offered beforeinstallprompt
  // (so the Add button really works). iOS Safari has no prompt API, so a short
  // "Tap Share -> Add to Home Screen" tip instead. Never inside an in-app browser
  // or when already running as the installed app.
  var INSTALL_KEY = "aangan.installHint.v1";
  var installPrompt = null, installHintLive = false;
  function nav() { return typeof navigator !== "undefined" ? navigator : {}; }
  function isStandalone() {
    try {
      if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) return true;
    } catch (e) { /* ignore */ }
    return nav().standalone === true;
  }
  function isIOS(ua) { return /iPhone|iPad|iPod/.test(ua || ""); }
  function installHintKind(ua) {
    if (isStandalone()) return null;
    if (installPrompt) return "prompt";
    if (isIOS(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua) && !inAppBrowser(ua)) return "ios";
    return null;
  }
  function installHint() {
    if (!store.onboarded || (isRealMode() && !window.Backend.user)) return "";
    var kind = installHintKind(nav().userAgent || "");
    if (!kind) return "";
    if (!installHintLive) {
      var seen = null;
      try { seen = localStorage.getItem(INSTALL_KEY); } catch (e) { /* ignore */ }
      if (seen) return "";
      try { localStorage.setItem(INSTALL_KEY, "1"); } catch (e) { /* ignore */ }
      installHintLive = true;
    }
    var body = kind === "prompt"
      ? "<b>Add " + esc(BRAND.name) + " to your home screen</b><span>Opens like an app, one tap away.</span>"
      : "<b>Add " + esc(BRAND.name) + " to your home screen</b><span>Tap Share → Add to Home Screen.</span>";
    return '<div class="card install-hint" id="install-hint"><span class="ih-i" aria-hidden="true">📲</span><div class="grow">' + body + "</div>" +
      (kind === "prompt" ? '<button class="btn btn-primary btn-sm" data-act="install-app" id="install-app">Add</button>' : "") +
      '<button class="icon-btn" data-act="install-dismiss" id="install-dismiss" aria-label="Dismiss">✕</button></div>';
  }

  V.home = function () {
    var circles = D.circles.map(function (c) {
      return '<a class="card circle-card" href="#circle/' + c.id + '" style="text-decoration:none;color:inherit"><span class="ce">' + c.emoji + "</span><b>" + esc(c.name) + "</b><span>" + c.members + " moms</span></a>";
    }).join("");
    var feed = allPosts().map(function (p) { return postCard(p); }).join("");
    return { tab: "home", html:
      '<div class="view">' + homeTop() +
      '<div class="hello"><h2>' + greeting() + ", " + esc(store.profile.nickname) + ' <span aria-hidden="true">🌼</span></h2><p>Here\'s what moms near you are talking about.</p></div>' + installHint() +
      '<div class="section" style="padding:0;margin-top:14px"><div class="section-head" style="padding:0 18px"><h2>Your circles</h2><span class="muted">Swipe →</span></div>' +
      '<div class="circles-row">' + circles + "</div></div>" +
      '<div class="kind-banner"><span class="kb-i">💛</span><div><b>A kind space, always</b><span>Supportive reactions only — no downvotes, no shaming.</span></div></div>' +
      '<div class="section-head" style="padding:0 18px"><h2>Fresh today</h2><span class="muted">' + allPosts().length + " posts</span></div>" +
      '<div class="feed">' + (feed || '<div style="text-align:center;padding:40px 20px;color:var(--text-muted)">Be the first to share. You\'re not alone.</div>') + "</div></div>" };
  };

  V.circle = function (id) {
    var c = circle(id);
    if (!c) return V.home();
    var posts = allPosts().filter(function (p) { return p.circle === id; });
    var joined = store.joined[id] !== false;
    return { tab: "home", html:
      '<div class="view"><div class="backbar"><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + '</button><span class="title">Circle</span></div>' +
      '<div class="card circle-hero"><span class="ce">' + c.emoji + '</span><div style="flex:1"><h2>' + esc(c.name) + '</h2><p class="tiny">' + esc(c.desc) + " · " + c.members + ' moms</p></div>' +
      '<button class="btn btn-sm ' + (joined ? "btn-ghost" : "btn-primary") + '" data-act="join" data-id="' + id + '">' + (joined ? "Joined ✓" : "Join") + "</button></div>" +
      '<div style="padding:0 14px 14px"><a class="btn btn-warm btn-block" href="#ask/' + id + '" style="text-decoration:none">' + icon("plus") + "Ask in this circle</a></div>" +
      '<div class="feed">' + (posts.length ? posts.map(function (p) { return postCard(p); }).join("") : emptyState("🌱", "Be the first to post here", "Your question could help another mom feel less alone.")) + "</div></div>" };
  };

  var askDraft = { circle: null, title: "", body: "", anon: null, nudge: null };
  V.ask = function (circleId) {
    if (circleId && circle(circleId)) askDraft.circle = circleId;
    if (askDraft.anon === null) askDraft.anon = store.profile.anonDefault;
    var picks = D.circles.map(function (c) {
      return '<button class="chip" data-act="ask-circle" data-id="' + c.id + '" aria-pressed="' + (askDraft.circle === c.id) + '">' + c.emoji + " " + esc(c.name) + "</button>";
    }).join("");
    var canPost = askDraft.title.trim().length > 4;
    return { tab: "ask", html:
      '<div class="view"><header class="topbar"><h1>Ask your circle</h1><button class="icon-btn" data-act="go" data-to="#home" aria-label="Close">' + icon("close") + "</button></header>" +
      '<div class="compose">' +
      '<div class="field"><span class="label">Circle <span class="tiny">(optional)</span></span><div class="circle-pick">' + picks + "</div></div>" +
      '<div class="field"><label for="ask-title">Your question</label><input class="input" id="ask-title" data-input="ask-title" maxlength="140" placeholder="e.g. How did you handle the first week of daycare?" value="' + esc(askDraft.title) + '"></div>' +
      '<div class="field"><label for="ask-body">Add details <span class="tiny">(optional)</span></label><textarea class="input" id="ask-body" data-input="ask-body" maxlength="1200" placeholder="Share as much or as little as you like. This is a safe space.">' + esc(askDraft.body) + "</textarea>" +
      '<p class="demo-link">✨ <button class="link" data-act="ask-demo" id="kindness-demo">See the kindness check in action</button></p></div>' +
      '<div class="card toggle-row" style="margin-top:16px"><div class="grow"><b>Post anonymously</b><span>' + (askDraft.anon ? 'Hidden from other moms. ' + esc(BRAND.name) + '\'s moderators can see who posted, for safety.' : "Shown as " + esc(store.profile.nickname)) + "</span></div>" + switchEl(askDraft.anon, "ask-anon", "Post anonymously") + "</div>" +
      '<div class="anon-preview">' + avatar(askDraft.anon ? null : store.profile.nickname, D.me.hue, "sm") + "<span>Posting as <b>" + (askDraft.anon ? "Anonymous mom" : esc(store.profile.nickname)) + "</b></span></div>" +
      '<div id="ask-nudge-slot">' + (askDraft.nudge ? nudgeHtml(askDraft.body || askDraft.title, askDraft.nudge, "ask") : "") + "</div>" +
      '<div style="margin-top:18px"><button class="btn btn-primary btn-block" data-act="ask-post" id="ask-post"' + (canPost ? "" : " disabled") + ">Post question</button>" +
      '<p class="tiny ask-hint" id="ask-hint" style="text-align:center;margin-top:6px;' + (canPost ? "display:none;" : "") + '">Add a title (at least 5 characters) to post</p></div>' +
      '<p class="tiny" style="text-align:center;margin-top:10px;font-weight:600">Moms supporting moms — not a replacement for your doctor or therapist.</p>' +
      '<p class="tiny" style="text-align:center;margin-top:4px">Be kind. Every mom here is doing her best. 💛</p>' +
      "</div></div>" };
  };

  var replyDraft = { pid: null, text: "", anon: null, nudge: null };
  V.q = function (id) {
    var p = post(id);
    if (!p) return V.home();
    if (replyDraft.pid !== id) replyDraft = { pid: id, text: "", anon: store.profile.anonDefault, nudge: null };
    var c = p.circle ? circle(p.circle) : null;
    var ans = answersFor(p).slice().sort(function (a, b) { return (b.expert ? 1 : 0) - (a.expert ? 1 : 0); });
    var list = ans.map(function (a) {
      var name = a.anon ? "Anonymous mom" : a.author;
      return '<article class="card answer ' + (a.expert ? "expert" : "") + '" id="answer-' + a.id + '">' +
        '<div class="post-head">' + avatar(a.anon ? null : a.author, a.hue) + '<div class="who"><b>' + esc(name) +
        (a.expert ? ' <span class="expert-badge">' + icon("check") + esc(a.expert.label) + "</span>" : "") + "</b><span>" +
        (a.expert ? esc(a.expert.role) + " · " : "") + esc(a.time) + "</span></div>" +
        '<button class="icon-btn" style="width:34px;height:34px;box-shadow:none;background:transparent" data-act="answer-menu" data-author="' + esc(a.author || "") + '" aria-label="More options">' + icon("more") + "</button></div>" +
        '<p class="body">' + esc(a.body) + '</p><div class="post-foot">' + reactionBar(p.id + "/" + a.id, a.reactions || {}) + "</div></article>";
    }).join("");
    return { tab: null, after: function () { var t = $("#reply-text"); if (t && t.value) { t.style.height = "auto"; t.style.height = Math.min(120, t.scrollHeight) + "px"; } }, html:
      '<div class="view" style="padding-bottom:0"><div class="backbar"><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + '</button><span class="title">' + (c ? (c.emoji + " " + esc(c.name)) : "Community") + "</span></div>" +
      '<div class="q-detail">' + postCard(p, { full: true }) + "</div>" +
      '<div class="answers-head"><h2>' + ans.length + " supportive " + (ans.length === 1 ? "reply" : "replies") + '</h2><span class="tiny">Kindest first</span></div>' +
      '<div class="answers">' + (list || emptyState("🤍", "No replies yet", "Share what worked for you — even a hug helps.")) + "</div>" +
      '<div style="height:16px"></div>' +
      '<div class="reply-box"><div id="reply-nudge-slot">' + (replyDraft.nudge ? nudgeHtml(replyDraft.text, replyDraft.nudge, "reply") : "") + "</div>" +
      '<div class="reply-anon">' + switchEl(replyDraft.anon, "reply-anon", "Reply anonymously") + "Reply " + (replyDraft.anon ? "anonymously" : "as " + esc(store.profile.nickname)) +
      '<span style="flex:1"></span><button class="link" style="font-size:12px" data-act="reply-demo" id="reply-kindness-demo">Try kindness check</button></div>' +
      '<div class="reply-inner"><textarea id="reply-text" data-input="reply-text" rows="1" placeholder="Write a kind reply…" aria-label="Write a reply">' + esc(replyDraft.text) + "</textarea>" +
      '<button class="send-btn" data-act="reply-send" aria-label="Send reply" id="reply-send">' + icon("send") + "</button></div></div>" +
      '<p class="tiny" style="text-align:center;margin-top:10px;font-weight:600">Moms supporting moms — not a replacement for your doctor or therapist.</p></div>' };
  };

  // DEMO MODE ONLY. The neighbourhood dots are fictional demo data, so the map is
  // drawn as a generic sample (no real place names) and captioned as such; real
  // mode never shows it (V.nearby renders an honest empty state instead).
  function mapSvg(activeHood) {
    var s = '<svg viewBox="0 0 340 220" role="img" aria-label="Sample neighbourhood map (demo data)">' +
      '<rect width="340" height="220" fill="#F7EEDF"/>' +
      '<path d="M0 0H340V26C290 40 236 22 176 36 112 50 64 30 0 44Z" fill="#D5E8E4"/>' +
      '<path d="M54 40c18-6 44-6 58 4 4 10-6 18-26 18-20 0-36-8-32-22z" fill="#D9E8CF"/>' +
      '<path d="M0 72C90 62 200 74 340 62" stroke="#EBCB9C" stroke-width="7" fill="none"/>' +
      '<path d="M0 134C100 128 220 122 340 116" stroke="#EADBC5" stroke-width="5" fill="none"/>' +
      '<path d="M112 44C118 100 102 160 120 220" stroke="#A9CFC9" stroke-width="2.5" fill="none" stroke-dasharray="1 0"/>' +
      '<path d="M162 66V220" stroke="#E6D6C2" stroke-width="1.5" stroke-dasharray="4 4" fill="none"/>' +
      '<text x="18" y="210" font-size="8.5" font-weight="700" fill="#8F7E74" letter-spacing="2" font-family="Plus Jakarta Sans">SAMPLE MAP · DEMO</text>';
    D.neighbourhoods.forEach(function (h) {
      var on = activeHood === h.id;
      s += '<g class="hood ' + (on ? "active" : "") + '" data-act="hood" data-id="' + h.id + '" tabindex="0" role="button" aria-label="' + esc(h.name) + ", about " + h.moms + ' moms">' +
        '<circle class="halo" cx="' + h.x + '" cy="' + h.y + '" r="' + (on ? 24 : 19) + '" fill="rgba(232,163,61,.22)"/>' +
        '<circle cx="' + h.x + '" cy="' + h.y + '" r="11" fill="' + (on ? "#1E4D4F" : "#B9572F") + '"/>' +
        '<text x="' + h.x + '" y="' + (h.y + 3.5) + '" font-size="9" font-weight="700" fill="#fff" text-anchor="middle" font-family="Plus Jakarta Sans">' + h.moms + "</text>" +
        '<text x="' + h.x + '" y="' + (h.y + 22) + '" font-size="7" font-weight="600" fill="#5E4A40" text-anchor="middle" font-family="Plus Jakarta Sans">' + esc(h.short) + "</text></g>";
    });
    return s + "</svg>";
  }

  // "Meetup feature" = everything that needs to know where she is: the Meetups tab
  // (list, RSVP, host) and Nearby moms (map, say-hi). Both show this card until a
  // city is set; feed, posting, replies, circles, chats and Me never need one.
  function cityGate(tab, title) {
    return { tab: tab, html:
      '<div class="view"><header class="topbar"><h1>' + title + "</h1></header>" +
      '<div class="card city-gate" id="city-gate"><span class="cg-i" aria-hidden="true">📍</span>' +
      "<h2>Add your city to use meetups</h2>" +
      '<p class="muted">Meetups and Nearby moms are local, so we need your city first. It\'s only used to show moms and meetups near you — the rest of ' + esc(BRAND.name) + " works without it.</p>" +
      cityField("gate-city", "Your city") +
      '<button class="btn btn-primary btn-block" data-act="save-city" data-src="gate-city" id="gate-save">Save</button></div></div>' };
  }

  var nearbyFilter = null;
  V.nearby = function () {
    if (!hasCity()) return cityGate("nearby", "Moms nearby");
    if (!store.nearbyOn) {
      return { tab: "nearby", html:
        '<div class="view"><div class="optin">' +
        '<svg class="optin-art" viewBox="0 0 220 170" aria-hidden="true"><circle cx="110" cy="88" r="78" fill="#FDE9DA"/><circle cx="110" cy="88" r="52" fill="#FCEFD3"/>' +
        '<circle cx="110" cy="88" r="26" fill="#E0EEEB"/><circle cx="62" cy="58" r="14" fill="#B9572F"/><circle cx="160" cy="70" r="14" fill="#1E4D4F"/><circle cx="138" cy="134" r="14" fill="#E8A33D"/><circle cx="74" cy="124" r="12" fill="#5A2D4C"/>' +
        '<text x="62" y="63" font-size="12" text-anchor="middle" fill="#fff" font-weight="700" font-family="Plus Jakarta Sans">PR</text><text x="160" y="75" font-size="12" text-anchor="middle" fill="#fff" font-weight="700" font-family="Plus Jakarta Sans">AK</text>' +
        '<text x="138" y="139" font-size="12" text-anchor="middle" fill="#fff" font-weight="700" font-family="Plus Jakarta Sans">SN</text><text x="74" y="128" font-size="10" text-anchor="middle" fill="#fff" font-weight="700" font-family="Plus Jakarta Sans">MV</text>' +
        '<path d="M110 74c-6 0-10 4-10 10 0 7 10 16 10 16s10-9 10-16c0-6-4-10-10-10z" fill="#1E4D4F"/><circle cx="110" cy="84" r="3.4" fill="#fff"/></svg>' +
        "<h1>Moms near you</h1>" +
        '<p class="lead">Find moms in your neighbourhood for walks, playdates and chai. You\'re invisible until you choose otherwise.</p>' +
        '<div class="optin-list">' +
        '<div class="row"><span class="oi">' + icon("pin") + "</span><div><b>Neighbourhood only</b>Others see \"Koramangala area · ~1 km\" — never your exact location.</div></div>" +
        '<div class="row"><span class="oi">' + icon("hand") + "</span><div><b>Mutual hellos</b>Chat unlocks only when you both say hi.</div></div>" +
        '<div class="row"><span class="oi">' + icon("eyeoff") + "</span><div><b>Hide anytime</b>Turn this off in one tap from your profile.</div></div></div>" +
        '<div class="card toggle-row"><div class="grow"><b>Show me to moms near me</b><span>Off by default</span></div>' + switchEl(false, "nearby-on", "Show me to moms near me", ' id="nearby-toggle"') + "</div>" +
        "</div></div>" };
    }
    var moms = D.moms.filter(function (m) { return store.blocked.indexOf(m.id) < 0 && (!nearbyFilter || m.area === nearbyFilter); });
    var cards = moms.map(function (m) {
      var st = momStatus(m), h = hood(m.area);
      var action = st === "accepted"
        ? '<a class="btn btn-primary btn-sm" href="#chat/' + m.id + '" style="text-decoration:none">' + icon("chat") + "Message</a>"
        : st === "pending" ? '<button class="btn btn-ghost btn-sm" disabled>' + icon("clock") + "Hi sent</button>"
        : '<button class="btn btn-warm btn-sm" data-act="say-hi" data-id="' + m.id + '" id="hi-' + m.id + '">👋 Say hi</button>';
      var note = st === "accepted" ? icon("check") + "You both said hi — chat is open"
        : st === "pending" ? icon("lock") + "Chat unlocks when " + esc(m.nickname) + " says hi back"
        : icon("lock") + "Chat unlocks after you both say hi";
      return '<article class="card mom" id="mom-' + m.id + '"><div class="mom-top">' + avatar(m.nickname, m.hue, "lg") +
        '<div class="grow"><b>' + esc(m.nickname) + '</b><span class="loc">' + icon("pin") + "<span>" + esc(h.name) + ' · <span style="white-space:nowrap">' + esc(m.distance) + "</span></span></span></div>" +
        '<button class="icon-btn" style="width:34px;height:34px" data-act="mom-menu" data-id="' + m.id + '" aria-label="More options">' + icon("more") + "</button></div>" +
        '<div class="rows"><div class="r"><span class="k">Kids</span><div class="chips">' + m.kids.map(function (k) { return '<span class="tag marigold">' + esc(k) + "</span>"; }).join("") + "</div></div>" +
        '<div class="r"><span class="k">Speaks</span><div class="chips">' + m.languages.map(function (k) { return '<span class="tag teal">' + esc(k) + "</span>"; }).join("") + "</div></div>" +
        '<div class="r"><span class="k">Into</span><div class="chips">' + m.interests.map(function (k) { return '<span class="tag plum">' + esc(k) + "</span>"; }).join("") + "</div></div></div>" +
        '<div class="mom-actions">' + action + "</div>" +
        '<p class="status-note">' + note + "</p></article>";
    }).join("");
    var fh = nearbyFilter && hood(nearbyFilter);
    var head = '<div class="view"><header class="topbar"><h1>Moms nearby</h1><a class="icon-btn" href="#chats" aria-label="Messages">' + icon("chat") + "</a></header>" + cityStrip();
    // Real mode has no nearby-moms backend yet: show an honest empty state for her
    // city rather than the fictional demo moms and sample map.
    if (isRealMode()) {
      return { tab: "nearby", html: head +
        '<div class="mom-list">' + emptyState("🌿", "No moms nearby in " + esc(store.city) + " yet", "You're on the list — as moms in your city turn this on, they'll show up here.") + "</div></div>" };
    }
    return { tab: "nearby", html: head +
      '<div class="card map-card">' + mapSvg(nearbyFilter) +
      '<div class="map-legend"><span>' + icon("shield") + "Neighbourhoods only · never exact spots</span><span>" + (fh ? '<button class="link" data-act="hood-clear">Show all</button>' : "Tap an area") + "</span></div></div>" +
      '<div class="section-head" style="padding:18px 18px 0"><h2>' + (fh ? esc(fh.name) : "Say hi to a mom") + '</h2><span class="muted">' + moms.length + " shown</span></div>" +
      '<div class="privacy-strip">' + icon("eyeoff") + "You're visible as \"" + esc(store.profile.nickname) + " · " + esc(store.city) + ' · neighbourhood only". <a class="link" href="#me" style="margin-left:auto">Change</a></div>' +
      '<div class="mom-list">' + (cards || emptyState("🌿", "No moms shown here yet", "Try another area — more moms join every week.")) + "</div></div>" };
  };

  // "📍 Pune · Change" line under the Meetups / Nearby headers.
  function cityStrip() {
    return '<p class="city-strip">' + icon("pin") + "<span>" + esc(store.city) + '</span><button class="link" data-act="edit-city" id="change-city">Change</button>' +
      (isRealMode() ? "" : '<span class="tiny">· sample data (demo)</span>') + "</p>";
  }

  var meetupsSeg = "all";
  V.meetups = function () {
    if (!hasCity()) return cityGate("meetups", "Meetups");
    var head = '<div class="view"><header class="topbar"><h1>Meetups</h1></header>' + cityStrip() +
      '<p class="muted" style="padding:0 18px 14px;margin-top:-6px;font-size:14px">Small, mom-hosted, in public places in ' + esc(store.city) + ".</p>";
    var host = '<div class="card host-cta"><span style="font-size:28px">🪔</span><div class="grow"><b>Host a meetup</b><span>Stroller walk, chai morning, toy swap — you pick.</span></div><button class="btn btn-ghost btn-sm" data-act="soon">Start</button></div>';
    // Real mode: meetups aren't stored in Firestore yet, so there is nothing real
    // to list -- never show the fictional demo events to a real mom.
    if (isRealMode()) {
      return { tab: "meetups", html: head +
        '<div class="events">' + emptyState("🗓️", "No meetups in " + esc(store.city) + " yet", "Be the first to host one — small, public and mom-led.") + "</div>" + host + "</div>" };
    }
    var evs = D.events.filter(function (e) { return meetupsSeg === "all" || store.rsvp[e.id]; });
    var list = evs.map(function (e) {
      var going = !!store.rsvp[e.id];
      var faces = D.moms.slice(0, 3).map(function (m) { return avatar(m.nickname, m.hue, "sm"); }).join("");
      return '<article class="card event" id="event-' + e.id + '"><div class="date-tile"><div class="m">' + e.month + '</div><div class="d">' + e.date + '</div><div class="w">' + e.day + "</div></div>" +
        '<div class="grow"><h3>' + e.emoji + " " + esc(e.title) + "</h3>" +
        '<div class="meta"><span>' + icon("clock") + esc(e.time) + "</span><span>" + icon("pin") + esc(e.place) + "</span></div>" +
        '<p class="desc">' + esc(e.desc) + '</p><div class="chips" style="margin-top:8px;gap:6px">' + e.tags.map(function (t) { return '<span class="tag">' + esc(t) + "</span>"; }).join("") + '<span class="tag teal">Hosted by ' + esc(e.host) + "</span></div>" +
        '<div class="event-foot"><span class="avatar-stack">' + faces + '</span><span class="going">' + (e.going + (going ? 1 : 0)) + " going</span>" +
        '<button class="btn btn-primary btn-sm rsvp" data-act="rsvp" data-id="' + e.id + '" aria-pressed="' + going + '" id="rsvp-' + e.id + '">' + (going ? icon("check") + "Going" : "RSVP") + "</button></div></div></article>";
    }).join("");
    return { tab: "meetups", html: head +
      '<div class="seg" role="tablist"><button data-act="seg" data-v="all" aria-pressed="' + (meetupsSeg === "all") + '">Upcoming</button><button data-act="seg" data-v="going" aria-pressed="' + (meetupsSeg === "going") + '">Going (' + Object.keys(store.rsvp).filter(function (k) { return store.rsvp[k]; }).length + ")</button></div>" +
      '<div class="events">' + (list || emptyState("🗓️", "Nothing yet", "RSVP to a meetup and it will show up here.")) + "</div>" +
      host + "</div>" };
  };

  var MOCK_REPLIES = ["That sounds lovely 😊", "Haha same here! Toddler life 😅", "Yes! Let's do it. Saturday works for me.", "Aww thank you, that means a lot 💛", "I'll bring the chai ☕"];
  V.chat = function (id) {
    var m = mom(id);
    if (!m) return V.chats();
    var blocked = store.blocked.indexOf(id) >= 0;
    var st = momStatus(m);
    if (!store.chats[id]) store.chats[id] = (D.chats[id] || []).slice();
    var msgs = store.chats[id].map(function (x) {
      return '<div class="msg ' + x.from + '">' + esc(x.text) + '<span class="t">' + esc(x.time) + "</span></div>";
    }).join("");
    var body;
    if (blocked) body = '<div class="blocked-note">' + icon("block", "") .replace('class=""', 'style="width:34px;height:34px"') + "<p style=\"margin-top:8px\"><b>You blocked " + esc(m.nickname) + "</b></p><p class=\"tiny\">She can't see your profile or message you. You can unblock from settings.</p></div>";
    else if (st !== "accepted") body = '<div class="blocked-note">' + icon("lock", "").replace('class=""', 'style="width:34px;height:34px"') + '<p style="margin-top:8px"><b>Chat is locked</b></p><p class="tiny">Chat unlocks once you both say hi.</p><a class="btn btn-warm btn-sm" style="margin-top:12px;text-decoration:none" href="#nearby">Go to Nearby</a></div>';
    else body = '<div class="msgs" id="msgs"><div class="safety-pill">🔒 You both said hi. Meet in public places first, and you can block or report anytime from ⋯</div><div class="day-sep">Today</div>' + msgs + "</div>" +
      '<div class="chat-input"><div class="reply-inner"><textarea id="chat-text" rows="1" placeholder="Message ' + esc(m.nickname) + '…" aria-label="Message"></textarea><button class="send-btn" data-act="chat-send" data-id="' + id + '" aria-label="Send" id="chat-send">' + icon("send") + "</button></div></div>";
    return { tab: null, after: function () { var el = $("#screen"); el.scrollTop = el.scrollHeight; }, html:
      '<div class="view chat-view" style="padding-bottom:0"><div class="chat-head"><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + "</button>" + avatar(m.nickname, m.hue) +
      '<div class="grow"><b>' + esc(m.nickname) + "</b><span>" + esc(hood(m.area).name) + " · " + esc(m.kids.join(", ")) + "</span></div>" +
      '<button class="icon-btn" data-act="chat-menu" data-id="' + id + '" aria-label="Block or report" id="chat-menu">' + icon("more") + "</button></div>" + body + "</div>" };
  };

  V.chats = function () {
    var rows = D.moms.filter(function (m) { return momStatus(m) === "accepted" && store.blocked.indexOf(m.id) < 0; }).map(function (m) {
      var msgs = store.chats[m.id] || D.chats[m.id] || [];
      var last = msgs[msgs.length - 1];
      return '<a class="card inbox-row" href="#chat/' + m.id + '" style="text-decoration:none;color:inherit">' + avatar(m.nickname, m.hue) + '<div class="grow"><b>' + esc(m.nickname) + "</b><span>" + esc(last ? last.text : "You both said hi — start the conversation!") + "</span></div>" + icon("chevron", "").replace('class=""', 'style="width:18px;height:18px;color:var(--ink-3)"') + "</a>";
    }).join("");
    var pending = D.moms.filter(function (m) { return momStatus(m) === "pending"; }).length;
    return { tab: null, html:
      '<div class="view"><div class="backbar"><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + '</button><span class="title">Messages</span></div>' +
      '<div class="inbox">' + (rows || emptyState("💬", "No chats yet", "Say hi to a mom nearby — chat opens when she says hi back.")) + "</div>" +
      (pending ? '<p class="footer-note">' + pending + " hello" + (pending > 1 ? "s" : "") + " waiting for a reply</p>" : "") +
      '<p class="footer-note">Only moms you\'ve both said hi to can message you.</p></div>' };
  };


  // Helplines re-verified 2026-10-09 against official pages:
  // - PSI (postpartum.net/get-help/psi-helpline/): call 1-800-944-4773 (#1 Espanol, #2 English);
  //   text "Help" to 800-944-4773 (English); text en Espanol 971-203-7773; messages returned daily
  //   8am-11pm ET; PSI says it is NOT a crisis hotline.
  // - 988 (988lifeline.org): call, text or chat (chat.988lifeline.org), 24/7/365, free, confidential;
  //   text and chat also in Spanish.
  // - National Maternal Mental Health Hotline 1-833-852-6262 / 1-833-TLC-MAMA (HRSA,
  //   mchb.hrsa.gov/national-maternal-mental-health-hotline): call or text, 24/7, English & Spanish.
  // Demo only: a real launch needs server-side moderation and trained human review.
  V.safety = function () {
    return { tab: "me", html:
      '<div class="view"><header class="topbar"><h1>Safety centre</h1><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + "</button></header>" +
      '<div class="card" style="margin-top:20px;text-align:center">' +
      '<div style="font-size:32px;margin-bottom:12px">🤍</div>' +
      '<h2 style="margin-bottom:8px">You deserve support right away</h2>' +
      '<p class="muted">The first two lines are free, confidential, and open 24/7.</p></div>' +
      '<div class="settings-group"><h3>National Maternal Mental Health Hotline</h3><p class="muted" style="font-size:13px;margin:0 4px 8px">Call or text 1-833-TLC-MAMA \u00b7 24/7 \u00b7 English &amp; Spanish</p><div class="card">' +
      '<a class="link-row" href="tel:18338526262" style="text-decoration:none;color:inherit">' + icon("phone") + '<span class="grow">Call 1-833-852-6262</span>' + icon("chevron") + "</a>" +
      '<a class="link-row" href="sms:18338526262" style="text-decoration:none;color:inherit">' + icon("chat") + '<span class="grow">Text 1-833-852-6262</span>' + icon("chevron") + "</a></div></div>" +
      '<div class="settings-group"><h3>988 Suicide & Crisis Lifeline</h3><p class="muted" style="font-size:13px;margin:0 4px 8px">Call, text or chat \u00b7 24/7 \u00b7 Spanish available</p><div class="card">' +
      '<a class="link-row" href="tel:988" style="text-decoration:none;color:inherit">' + icon("phone") + '<span class="grow">Call 988</span>' + icon("chevron") + "</a>" +
      '<a class="link-row" href="sms:988" style="text-decoration:none;color:inherit">' + icon("chat") + '<span class="grow">Text 988</span>' + icon("chevron") + "</a>" +
      '<a class="link-row" href="https://chat.988lifeline.org/" target="_blank" rel="noopener" style="text-decoration:none;color:inherit">' + icon("chat") + '<span class="grow">Chat online at 988lifeline.org</span>' + icon("chevron") + "</a></div></div>" +
      '<div class="settings-group"><h3>Postpartum Support International (support, not a crisis line)</h3><p class="muted" style="font-size:13px;margin:0 4px 8px">Leave a message any day \u2014 they reply 8am\u201311pm ET. English &amp; Spanish.</p><div class="card">' +
      '<a class="link-row" href="tel:18009444773" style="text-decoration:none;color:inherit">' + icon("phone") + '<span class="grow">Call 1-800-944-4773 (#1 Espa\u00f1ol, #2 English)</span>' + icon("chevron") + "</a>" +
      '<a class="link-row" href="sms:18009444773&body=HELP" style="text-decoration:none;color:inherit">' + icon("chat") + '<span class="grow">Text \u201cHelp\u201d to 800-944-4773 (English)</span>' + icon("chevron") + "</a>" +
      '<a class="link-row" href="sms:19712037773" style="text-decoration:none;color:inherit">' + icon("chat") + '<span class="grow">Texto en espa\u00f1ol: 971-203-7773</span>' + icon("chevron") + "</a></div></div>" +
      '<p class="footer-note">If you or your baby are in immediate danger, call 911.<br><br>Moms supporting moms \u2014 not a replacement for your doctor or therapist.</p>' +
      "</div>" };
  };

  // ------------------------------------------------------- privacy & terms
  // #privacy: plain, warm Privacy & Terms, linked from the welcome screen, the
  // feedback footer and a Me row. Every "what we store" line mirrors what
  // backend.js actually writes (profiles incl. Google fullName/email, posts/replies
  // with uid + anon flag, reactions, reports, feedback with page + browser) and
  // firestore.rules (profiles are owner-only, so other moms never read an email).
  // Deliberately no email address and no mail link: deletion requests go through
  // "Send feedback" while signed in, which ties the request to her account uid.
  // NOT LEGAL ADVICE: a plain-language draft for a small beta. Have a lawyer review
  // it (incl. India's DPDP Act and GDPR/US state laws for moms abroad) before launch.
  var PRIVACY_UPDATED = "9 October 2026";
  function privacySection(emoji, title, body) {
    return '<section class="settings-group privacy-sec"><h3><span aria-hidden="true">' + emoji + "</span> " + title + '</h3><div class="card privacy-card">' + body + "</div></section>";
  }
  V.privacy = function () {
    var name = esc(BRAND.name);
    return { tab: null, html:
      '<div class="view privacy-view"><header class="topbar"><h1>Privacy &amp; Terms</h1><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + "</button></header>" +
      '<div class="card privacy-intro"><div style="font-size:30px;margin-bottom:8px" aria-hidden="true">🤍</div>' +
      "<p>" + name + " is a small, kind corner of the internet for moms. Here is, in plain words, who can join, what we keep, who sees what, and the few rules that keep it safe.</p></div>" +
      privacySection("🌸", "Who can join",
        "<p>" + name + " is for women aged 18 and over who are moms or moms-to-be. One account per person, please.</p>") +
      privacySection("🗂️", "What we store",
        "<p>When you sign in with Google, we receive your <b>name, email address and profile photo</b> from Google. We keep your name and email on your private profile so we know the account is yours.</p>" +
        "<p>We also store what you add: your nickname, the stages and languages you pick, your <b>city if you add it</b>, your <b>posts and replies</b> (and whether each one is anonymous), the <b>reactions</b> you give, any posts you report, and <b>feedback notes</b> you send (with the page you sent them from and your browser type).</p>" +
        "<p>All of this lives in <b>Google Firebase</b> (Firebase Authentication and Cloud Firestore). A few settings are also kept in your browser on this device.</p>") +
      privacySection("👀", "What other moms see",
        "<p>Other moms see your <b>nickname</b> (or <b>\u201cAnonymous mom\u201d</b>), your posts, your replies and reaction counts. They <b>never</b> see your email address, and your profile is readable only by you.</p>") +
      privacySection("🫶", "Anonymous posts",
        "<p>When you post anonymously, other moms see \u201cAnonymous mom\u201d instead of your name. The post is still saved with your account, so you can manage it and so moderators can act if it is reported.</p>") +
      privacySection("🩺", "Not medical advice",
        "<p>Moms supporting moms \u2014 " + name + " is not a replacement for your doctor, midwife or therapist. Advice here comes from other moms\u2019 experience, not from professionals.</p>" +
        '<p><b>In an emergency, call your local emergency number now</b> (112 in India, 911 in the US and Canada, 999 in the UK). For support lines, see the <a href="#safety" id="privacy-safety">Safety centre &amp; crisis lines</a>.</p>') +
      privacySection("🤝", "Community rules",
        "<ul class=\"privacy-list\"><li>Be kind. No shaming, bullying or judging another mom\u2019s choices.</li>" +
        "<li>No ads, selling or spam.</li>" +
        "<li>No medical misinformation. Share your experience, and encourage moms to check with their doctor.</li>" +
        "<li>Respect privacy: don\u2019t share another person\u2019s photos or personal details.</li></ul>" +
        "<p>Moderators may remove posts or replies that break these rules, and may remove accounts that keep breaking them.</p>") +
      privacySection("🗑️", "Deleting your account and data",
        "<p>Sign in, tap <b>\u201cSend feedback\u201d</b> and write <b>\u201cDelete my account\u201d</b>. Because you are signed in, we know which account it is. We will delete your account and the data linked to it (profile, posts, replies, reactions and feedback) <b>within 30 days</b>.</p>") +
      privacySection("🚫", "No ads, no selling",
        "<p>We don\u2019t show ads and we never sell your data.</p>") +
      privacySection("📝", "Changes to these terms",
        "<p>If we change these terms, we will update this page and the date below. Using " + name + " after a change means you accept the updated terms.</p>") +
      '<p class="footer-note" id="privacy-updated">Last updated: ' + PRIVACY_UPDATED + "</p>" +
      "</div>" };
  };

  V.me = function () {
    var p = store.profile;
    var authMethodLabel = (store.authMethod === "google" || store.verify.google) ? "Google" : "phone";
    var policy = [
      ["mutual", "Only moms I've said hi to", "Recommended · chat after a mutual hello"],
      ["verified", "Any verified mom", "Still women-only and verified"],
      ["none", "No one for now", "Pause all new messages"]
    ].map(function (o) {
      return '<button class="radio-row" role="radio" aria-checked="' + (store.msgPolicy === o[0]) + '" data-act="policy" data-v="' + o[0] + '"><span class="grow"><b>' + o[1] + "</b><span>" + o[2] + '</span></span><span class="radio"></span></button>';
    }).join("");
    return { tab: "me", html:
      '<div class="view"><header class="topbar"><h1>Me</h1></header>' +
      '<div class="card profile-card">' + avatar(p.nickname, D.me.hue, "xl") +
      "<h2>" + esc(p.nickname) + '</h2><span class="verified">' + icon("shield") + "Verified mom · " + authMethodLabel + "</span>" +
      '<div class="chips">' + p.stages.map(function (s) { return '<span class="tag marigold">' + esc(s) + "</span>"; }).join("") + p.langs.map(function (s) { return '<span class="tag teal">' + esc(s) + "</span>"; }).join("") + "</div>" +
      '<div class="stats"><div><b>' + (2 + store.posts.length) + "</b><span>Questions</span></div><div><b>" + (7 + Object.keys(store.answers).reduce(function (n, k) { return n + store.answers[k].length; }, 0)) + "</b><span>Replies</span></div><div><b>" + (31 + Object.keys(store.reacted).length) + "</b><span>Hugs given</span></div></div></div>" +
      '<div class="settings-group"><h3>Privacy</h3><div class="card">' +
      '<div class="toggle-row"><div class="grow"><b>Post anonymously by default</b><span>Switch per post anytime</span></div>' + switchEl(p.anonDefault, "toggle-anon-default", "Post anonymously by default", ' id="set-anon"') + "</div>" +
      '<div class="toggle-row"><div class="grow"><b>Show me to moms near me</b><span>Neighbourhood only · never exact location</span></div>' + switchEl(store.nearbyOn, "nearby-toggle", "Show me to moms near me", ' id="set-nearby"') + "</div></div></div>" +
      '<div class="settings-group"><h3>Who can message me</h3><div class="card" role="radiogroup">' + policy + "</div></div>" +
      '<div class="settings-group"><h3>Safety</h3><div class="card">' +
      '<button class="link-row" data-act="blocked-list">' + icon("block") + '<span class="grow">Blocked moms</span><span class="tiny">' + store.blocked.length + "</span>" + icon("chevron") + "</button>" +
      '<button class="link-row" data-act="guidelines">' + icon("book") + '<span class="grow">Community guidelines</span>' + icon("chevron") + "</button>" +
      (canModerate() ? '<a class="link-row" href="#mod" id="open-mod" style="text-decoration:none;color:inherit">' + icon("flag") + '<span class="grow">Moderation' + (isRealMode() ? "" : " (demo)") + '</span><span class="tiny">' + modReports().length + " open</span>" + icon("chevron") + "</a>" : "") +
      '<a class="link-row" href="#safety" style="text-decoration:none;color:inherit">' + icon("shield") + '<span class="grow">Safety centre & crisis lines</span>' + icon("chevron") + "</a></div></div>" +
      '<div class="settings-group"><h3>Account</h3><div class="card">' +
      '<button class="link-row" data-act="edit-city" id="me-city">' + icon("pin") + '<span class="grow">City</span><span class="tiny" id="me-city-value">' + (hasCity() ? esc(store.city) : "Not set · needed for meetups") + "</span>" + icon("chevron") + "</button>" +
      ((window.Backend && window.Backend.isReal) ? 
        (window.Backend.user ? '<div class="link-row uid-row"><span class="grow"><b>Your account ID</b><span class="tiny" id="my-uid">' + esc(window.Backend.user.uid) + '</span></span><button class="btn btn-ghost btn-sm" data-act="copy-uid" id="copy-uid">Copy</button></div>' : "") +
        '<button class="link-row" data-act="sign-out" id="sign-out">' + icon("reset") + '<span class="grow">Sign out</span>' + icon("chevron") + "</button></div></div>" :
        '<button class="link-row" data-act="reset" id="reset-demo">' + icon("reset") + '<span class="grow">Reset demo</span>' + icon("chevron") + "</button></div></div>") +
      '<div class="settings-group"><h3>Help us improve</h3><div class="card">' +
      '<button class="link-row" data-act="feedback" id="me-feedback"><span aria-hidden="true">💬</span><span class="grow">Send feedback</span><span class="tiny">Tell us what you think</span>' + icon("chevron") + "</button>" +
      '<a class="link-row" href="#privacy" id="me-privacy" style="text-decoration:none;color:inherit"><span aria-hidden="true">📄</span><span class="grow">Privacy &amp; Terms</span><span class="tiny">What we store, the rules</span>' + icon("chevron") + "</a></div></div>" +
      '<p class="footer-note">' + esc(BRAND.name) + (isRealMode() ? " · v0.1 · beta" : " prototype · v0.1 · all data is fictional") + "</p></div>" };
  };

  // ----------------------------------------------------------- moderation
  // Real mode: shown only to moderators (a /moderators/{uid} doc made by hand in the
  // Firebase console). Hiding the screen is cosmetic -- firestore.rules isModerator()
  // is what actually allows reading/deleting reports and deleting others' posts.
  // Demo mode: everyone is a pretend moderator over reports kept in localStorage.
  function isRealMode() { return !!(window.Backend && window.Backend.isReal); }
  function canModerate() { return isRealMode() ? modState.isMod : true; }
  function modReports() { return isRealMode() ? modState.reports : (store.reports || []); }
  // undefined = still loading, null = gone. Reported posts outside the feed's latest
  // 100 are fetched once and cached for the session.
  function modPost(pid) {
    var p = post(pid);
    if (p) return p;
    if (!isRealMode()) return null;
    if (Object.prototype.hasOwnProperty.call(modState.postCache, pid)) return modState.postCache[pid];
    if (!modState.fetching[pid] && window.Backend.getPost) {
      modState.fetching[pid] = true;
      window.Backend.getPost(pid).then(function (d) {
        modState.postCache[pid] = d;
        if (parseHash().name === "mod") rerender();
      }).catch(function (e) { console.error("MomSakhi: couldn't load reported post", e); modState.postCache[pid] = null; });
    }
    return undefined;
  }
  V.mod = function () {
    var head = '<div class="view"><header class="topbar"><h1>Moderation</h1><button class="icon-btn" data-act="back" aria-label="Back">' + icon("back") + "</button></header>";
    if (!canModerate()) return { tab: "me", html: head + emptyState("🔒", "Moderators only", "This page is for " + esc(BRAND.name) + " moderators.") + "</div>" };
    var list = modReports().map(function (r) {
      var p = modPost(r.postId);
      var title = p ? (p.title || "(no title)") : (p === null ? "Post already removed or not found" : "Loading post…");
      var body = p && p.body ? String(p.body) : "";
      if (body.length > 160) body = body.slice(0, 160) + "…";
      return '<article class="card mod-item" id="mod-' + esc(r.id) + '">' +
        '<div class="mod-meta"><span class="tag marigold">' + esc(r.reason || "Reported") + '</span><span class="tiny">' + esc(formatTime(r.createdAt)) + "</span></div>" +
        '<h3 class="mod-title">' + esc(title) + "</h3>" + (body ? '<p class="muted mod-body">' + esc(body) + "</p>" : "") +
        '<div class="mod-actions">' +
        '<button class="btn btn-danger btn-sm" data-act="mod-remove" data-id="' + esc(r.id) + '" data-pid="' + esc(r.postId) + '">Remove post</button>' +
        '<button class="btn btn-ghost btn-sm" data-act="mod-keep" data-id="' + esc(r.id) + '">Keep (dismiss report)</button>' +
        "</div></article>";
    }).join("");
    // Feedback (real mode only): read-only, newest first. Rules let only moderators read it.
    var fb = isRealMode() ? (modState.feedback || []) : [];
    var fbList = fb.map(function (f) {
      return '<article class="card mod-item fb-item" id="fb-' + esc(f.id) + '">' +
        '<div class="mod-meta"><span class="tag teal">' + esc(feedbackKindLabel(f.kind)) + '</span><span class="tiny">' + esc(formatTime(f.createdAt)) + (f.contactOk ? " · OK to contact" : "") + "</span></div>" +
        '<p class="mod-body">' + esc(f.text) + "</p>" + (f.page ? '<p class="tiny">Sent from ' + esc(f.page) + "</p>" : "") + "</article>";
    }).join("");
    var fbSection = isRealMode() ? '<div class="section-head" style="padding:0 18px"><h2>Feedback</h2><span class="muted">' + fb.length + "</span></div>" +
      (fbList || emptyState("💬", "No feedback yet", "Notes from moms show up here, newest first.")) : "";
    return { tab: "me", html: head +
      '<p class="muted" style="padding:0 18px 6px;font-size:14px">' + (isRealMode() ? "Reported posts, newest first. Removing deletes the post, its replies and its reports for everyone." : "Demo mode: reports you make on this device show up here.") + "</p>" +
      (list || emptyState("🌿", "No open reports", "All clear. Thank you for keeping " + esc(BRAND.name) + " kind.")) + fbSection + "</div>" };
  };

  // --------------------------------------------------------------- router
  var TABS = [
    { id: "home", href: "#home", label: "Home", icon: "home" },
    { id: "nearby", href: "#nearby", label: "Nearby", icon: "pin" },
    { id: "ask", href: "#ask", label: "Ask", icon: "plus", fab: true },
    { id: "meetups", href: "#meetups", label: "Meetups", icon: "calendar" },
    { id: "me", href: "#me", label: "Me", icon: "user" }
  ];
  function parseHash() {
    var h = (location.hash || "").replace(/^#\/?/, "");
    if (!h) return { name: store.onboarded ? "home" : "welcome", arg: null };
    if (h.indexOf("onboard/") === 0) return { name: h, arg: null };
    var i = h.indexOf("/");
    return i < 0 ? { name: h, arg: null } : { name: h.slice(0, i), arg: decodeURIComponent(h.slice(i + 1)) };
  }
  var lastRoute = "";
  var FEEDBACK_FOOT_TABS = ["home", "nearby", "meetups"];
  function render(keepScroll) {
    var r = parseHash();
    var view = V[r.name] || V.home;
    var out = view(r.arg);
    var screen = $("#screen");
    var y = screen.scrollTop;
    screen.innerHTML = out.html;
    // "💬 Send feedback" sits at the end of the main tab screens (Me has its own row).
    if (FEEDBACK_FOOT_TABS.indexOf(out.tab) >= 0) { var fv = screen.querySelector(".view"); if (fv) fv.insertAdjacentHTML("beforeend", feedbackFoot()); }
    var routeKey = r.name + "/" + (r.arg || "");
    if (keepScroll && routeKey === lastRoute) {
      screen.scrollTop = y;
      var v = screen.querySelector(".view"); if (v) v.style.animation = "none";
    } else screen.scrollTop = 0;
    lastRoute = routeKey;
    var tabbar = $("#tabbar");
    var dtLogo = $("#dt-logo");
    if (dtLogo) dtLogo.innerHTML = logoMark() + '<span class="logo-word" style="font-size:22px">' + esc(BRAND.name) + '</span>';
    var isPreAuth = out.tab === null || ["onboard/city", "onboard/about", "onboard/verify"].indexOf(r.name) >= 0 || r.name === "welcome";
    // The centred "onboarding-mode" layout is for welcome + onboarding steps ONLY.
    // Other tab-less views (#q/<id>, #chat/<id>, #chats) used to inherit it, which on
    // laptop widths laid the post, replies and reply box out side-by-side in one row
    // (found in the 2026-10-09 two-user emulator test).
    var isOnboarding = r.name === "welcome" || r.name.indexOf("onboard/") === 0;
    var app = $("#app");
    if (app) app.classList.toggle("onboarding-mode", isOnboarding);
    document.body.setAttribute("data-view", r.name);

    // Tab bar: always hidden on welcome/onboarding. On tab-less detail pages
    // (#q/<id> post, #chat/<id>) it is NOT [hidden]; instead the "detail-nav" class
    // hides it on phones (bottom bar would crowd the reply/chat box) and styles.css
    // shows it again >= 900px, so laptops keep the top menu next to the ← button.
    // #chats keeps its old behaviour (bar visible everywhere).
    // #privacy opened from the welcome screen (not joined yet) hides it entirely,
    // so a visitor reading the terms isn't offered app tabs she can't use yet.
    var isDetail = !isOnboarding && out.tab === null && r.name !== "chats";
    tabbar.hidden = isOnboarding || (r.name === "privacy" && !store.onboarded);
    tabbar.classList.toggle("detail-nav", isDetail);
    var tabLinks = $("#tab-links") || tabbar;
    tabLinks.innerHTML = TABS.map(function (t) {
      var cur = out.tab === t.id ? ' aria-current="page"' : "";
      var ic = t.fab ? '<span class="ask-fab">' + icon(t.icon) + "</span>" : icon(t.icon);
      return '<a class="tab" href="' + t.href + '"' + cur + ' id="tab-' + t.id + '">' + ic + "<span>" + t.label + "</span></a>";
    }).join("");
    document.title = BRAND.name + " — " + BRAND.tagline;
    
    var rightRail = $("#right-rail");
    if (rightRail) {
      if (isPreAuth) {
        rightRail.hidden = true;
      } else {
        rightRail.hidden = false;
        rightRail.innerHTML = '<div class="rr-section"><h3>Your Circles</h3>' + 
          D.circles.slice(0, 3).map(function(c) { return '<a class="rr-link" href="#circle/' + c.id + '">' + c.emoji + ' ' + esc(c.name) + '</a>'; }).join('') + 
          '</div>' +
          '<div class="rr-section"><h3>Upcoming Meetups</h3>' + 
          (!hasCity() ? '<a class="rr-link" href="#meetups">📍 Add your city to see meetups</a>'
            : isRealMode() ? '<p class="tiny">No meetups in ' + esc(store.city) + " yet.</p>"
            : D.events.slice(0, 2).map(function(e) { return '<a class="rr-link" href="#meetups">🗓️ ' + esc(e.title) + '</a>'; }).join('')) + 
          '</div>' +
          '<div class="rr-section"><h3>Kindness Guidelines</h3><p class="tiny">Supportive reactions only — no downvotes, no shaming. A safe space for moms.</p></div>' +
          '<div class="rr-section"><a href="#safety" class="rr-link" style="color:var(--plum);font-weight:600">🤍 Need help now?</a></div>';
      }
    }

    if (out.after) out.after();
  }
  function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

  // ---------------------------------------------------------- sheet/toast
  var toastTimer;
  function toast(msg) {
    var t = $("#toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2600);
  }
  // Every real-mode Firebase call ends in .catch(failToast(...)): the mom sees what
  // failed (e.g. "Couldn't post yet (permission-denied)") and the console keeps the
  // full error for debugging. `btn` (optional) is re-enabled so she can retry.
  function errCode(e) { return String((e && (e.code || e.message)) || "error").replace(/^(firestore|auth)\//, ""); }
  function failToast(what, btn) {
    return function (e) {
      console.error("MomSakhi: couldn't " + what, e);
      if (btn) btn.disabled = false;
      toast("Couldn't " + what + " yet (" + errCode(e) + "). Please try again.");
    };
  }
  function busy(btn) { if (btn && btn.tagName === "BUTTON") btn.disabled = true; return btn; }
  function openSheet(html) {
    var s = $("#sheet"), b = $("#sheet-backdrop");
    s.innerHTML = html; s.hidden = false; b.hidden = false;
    var first = s.querySelector("button"); if (first) first.focus();
  }
  function closeSheet() { $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true; }

  // ------------------------------------------------------------- feedback
  // "💬 Send feedback" (footer of the main tabs + a row on Me). Signed-in real mode
  // writes /feedback (write-only for moms; only moderators can read it -- see
  // firestore.rules). Signed out / demo: there's no safe inbox to mail, so we
  // just say "Sign in to send feedback". The draft survives closing the sheet and
  // a failed send, so she never loses what she wrote.
  var FEEDBACK_MAX = 1000;
  var FEEDBACK_KINDS = [["idea", "Idea"], ["bug", "Bug"], ["unsafe", "Something felt unsafe"], ["other", "Other"]];
  function freshFeedback() { return { text: "", kind: null, contactOk: false, sending: false }; }
  var fbDraft = freshFeedback();
  function feedbackKindLabel(k) { for (var i = 0; i < FEEDBACK_KINDS.length; i++) if (FEEDBACK_KINDS[i][0] === k) return FEEDBACK_KINDS[i][1]; return "Feedback"; }
  function feedbackFoot() {
    return '<div class="feedback-foot"><button class="feedback-link" data-act="feedback" id="feedback-open">💬 Send feedback</button>' +
      '<a class="feedback-link" href="#privacy" id="privacy-foot">📄 Privacy &amp; Terms</a></div>';
  }
  function feedbackSheetHtml() {
    var kinds = FEEDBACK_KINDS.map(function (k) {
      return '<button class="chip" data-act="fb-kind" data-v="' + k[0] + '" aria-pressed="' + (fbDraft.kind === k[0]) + '">' + icon("check", "check") + esc(k[1]) + "</button>";
    }).join("");
    var canSend = !!fbDraft.text.trim() && !fbDraft.sending;
    return '<div class="fb-sheet" id="fb-sheet"><h3>Send feedback</h3>' +
      '<p class="tiny">What do you think of ' + esc(BRAND.name) + '? Only the ' + esc(BRAND.name) + ' team reads these notes.</p>' +
      '<div class="field"><label for="fb-text">Your feedback</label>' +
      '<textarea class="input" id="fb-text" data-input="fb-text" maxlength="' + FEEDBACK_MAX + '" rows="4" placeholder="What did you like? What was confusing or missing?">' + esc(fbDraft.text) + "</textarea>" +
      '<p class="hint" id="fb-count">' + fbDraft.text.length + " / " + FEEDBACK_MAX + "</p></div>" +
      '<div class="field"><span class="label">What kind? <span class="tiny">(optional)</span></span><div class="chips">' + kinds + "</div></div>" +
      '<div class="toggle-row"><div class="grow"><b>OK to contact me</b><span>We may reach out about this note</span></div>' + switchEl(fbDraft.contactOk, "fb-contact", "OK to contact me", ' id="fb-contact"') + "</div>" +
      '<div class="fb-actions"><button class="btn btn-ghost" data-act="sheet-close" id="fb-cancel">Cancel</button>' +
      '<button class="btn btn-primary" data-act="fb-send" id="fb-send"' + (canSend ? "" : " disabled") + ">" + (fbDraft.sending ? "Sending…" : "Send") + "</button></div></div>";
  }
  function openFeedback() {
    var B = window.Backend;
    if (!isRealMode() || !B.user || !B.addFeedback) { toast("Sign in to send feedback"); return; }
    openSheet(feedbackSheetHtml());
    var t = $("#fb-text"); if (t) t.focus();
  }
  function sendFeedback(el) {
    var B = window.Backend;
    if (fbDraft.sending) return; // debounce double submits
    if (!isRealMode() || !B.user) { toast("Sign in to send feedback"); return; }
    var txt = fbDraft.text.trim().slice(0, FEEDBACK_MAX);
    if (!txt) { toast("Write a few words first 💛"); return; }
    fbDraft.sending = true; busy(el); el.textContent = "Sending…";
    var ua = (window.navigator && navigator.userAgent ? String(navigator.userAgent) : "").slice(0, 150);
    B.addFeedback(B.user.uid, txt, fbDraft.kind, fbDraft.contactOk, location.hash || "#home", ua).then(function () {
      fbDraft = freshFeedback(); closeSheet(); toast("Thank you 💛 We read every note.");
    }).catch(function (e) {
      fbDraft.sending = false; el.textContent = "Send"; // text kept for a retry
      failToast("send your feedback", el)(e);
    });
  }
  function reportSheet(opts) {
    var sheetEl = document.getElementById("sheet");
    if (sheetEl) { if (opts.postId) sheetEl.setAttribute("data-pid", opts.postId); else sheetEl.removeAttribute("data-pid"); }
    // opts: {title, subject, author, postId, momId}
    var items = '<button class="sheet-item" data-act="report-start" data-label="' + esc(opts.subject) + '">' + icon("flag") + "<span>Report " + esc(opts.subject) + "<small>Unkind, unsafe, spam or not from a mom</small></span></button>";
    if (opts.postId) items += '<button class="sheet-item" data-act="hide-post" data-id="' + opts.postId + '">' + icon("eyeoff") + "<span>Hide this post<small>You won't see it again</small></span></button>";
    if (opts.author || opts.momId) items += '<button class="sheet-item danger" data-act="block" data-who="' + esc(opts.momId || opts.author) + '" data-name="' + esc(opts.name || opts.author) + '">' + icon("block") + "<span>Block " + esc(opts.name || opts.author) + "<small>They won't see you or be able to message you</small></span></button>";
    items += '<button class="sheet-item" data-act="sheet-close">' + icon("close") + "<span>Cancel</span></button>";
    openSheet("<h3>" + esc(opts.title) + '</h3><p class="muted">Reports are anonymous. Our moderators review every one within 24 hours.</p><div class="sheet-list">' + items + "</div>");
  }

  // ------------------------------------------------------------- auth (demo)
  /* signInWithGoogle: Demo stub simulating Google OAuth account selection.
   *
   * In production with Firebase Auth, replace this demo stub with:
   *   import { getAuth, signInWithPopup, GoogleAuthProvider } from "firebase/auth";
   *   const auth = getAuth();
   *   const provider = new GoogleAuthProvider();
   *   provider.addScope("profile");
   *   provider.addScope("email");
   *   try {
   *     const result = await signInWithPopup(auth, provider);
   *     const user = result.user; // user.displayName, user.email, user.photoURL
   *     // Sync user profile to Firestore / store
   *   } catch (error) {
   *     console.error("Google sign-in failed:", error);
   *   }
   *
   * Requirements for production:
   *   1. A configured Firebase project with Google sign-in provider enabled in Firebase Console.
   *   2. OAuth 2.0 Web Client ID registered in Google Cloud Console with authorized redirect URIs.
   *   3. Firebase SDK scripts / bundle (firebase/app, firebase/auth) initialized with project config.
   * No API keys or external Firebase scripts are loaded in this static prototype.
   */
  // Shared by the popup path and the redirect path (getRedirectResult on load).
  function afterGoogleSignIn(u) {
    store.authMethod = "google";
    store.verify.google = true;
    var firstName = u.displayName ? (u.displayName.split(" ")[0] || u.displayName) : "Mom";
    store.profile.nickname = firstName;
    store.profile.fullName = u.displayName || "";
    store.profile.email = u.email || "";
    save();
    return window.Backend.getProfile(u.uid).then(function(p) {
      if (p) {
        applyProfile(p);
        store.onboarded = true;
        save();
        go("#home");
      } else {
        toast("Signed in ✓");
        go("#onboard/city");
      }
    }).catch(function (e) {
      failToast("load your profile", null)(e);
      go("#onboard/city");
    });
  }
  function signInWithGoogle(account, btn) {
    if (window.Backend && window.Backend.isReal) {
      busy(btn);
      // Backend falls back to signInWithRedirect for popup-blocked & co; in that
      // case the page navigates away and the result lands via getRedirectResult.
      window.Backend.signInWithGoogle().then(function(result) {
         if (btn) btn.disabled = false;
         if (!result || result.redirecting || !result.user) return;
         return afterGoogleSignIn(result.user);
      }).catch(function(e) {
         if (btn) btn.disabled = false;
         if (e && e.code === "auth/popup-closed-by-user") { toast("Sign-in cancelled"); return; }
         if (isWebviewAuthError(e)) { console.warn("MomSakhi: sign-in blocked in this browser", e); showSignInBlocked(); return; }
         failToast("sign you in", btn)(e);
      });
      return;
    }
    if (!account) {
      openGoogleChooser();
      return;
    }
    store.authMethod = "google";
    store.verify.google = true;
    var firstName = account.name ? (account.name.split(" ")[0] || account.name) : "Priya";
    store.profile.nickname = firstName;
    store.profile.fullName = account.name || "Priya Sharma";
    store.profile.email = account.email || "priya.sharma@gmail.com";
    save();
    toast("Signed in as " + store.profile.fullName + " ✓");
    go("#onboard/city");
  }

  function openGoogleChooser() {
    var accounts = [
      { name: "Priya Sharma", email: "priya.sharma@gmail.com", initial: "P", color: "#6366F1" },
      { name: "Ananya Iyer", email: "ananya.iyer@gmail.com", initial: "A", color: "#0D9488" }
    ];
    var accHtml = accounts.map(function (a) {
      return '<button class="sheet-item gc-account-item" data-act="pick-google-account" data-name="' + esc(a.name) + '" data-email="' + esc(a.email) + '">' +
        '<span class="avatar sm" style="background:' + a.color + ';color:#fff">' + a.initial + '</span>' +
        '<span class="grow"><b>' + esc(a.name) + '</b><small>' + esc(a.email) + '</small></span></button>';
    }).join("");
    accHtml += '<button class="sheet-item gc-account-item" data-act="pick-google-another">' +
      '<span class="avatar sm" style="background:#F1F5F9;color:#475569">' + icon("user") + '</span>' +
      '<span class="grow"><b>Use another account</b></span></button>';

    var html = '<div class="google-chooser">' +
      '<div class="gc-header">' + googleIcon(28) +
      '<h3>Choose an account</h3><p class="muted">to continue to ' + esc(BRAND.name) + '</p></div>' +
      '<div class="sheet-list gc-accounts">' + accHtml + '</div>' +
      '<p class="tiny muted gc-disclaimer">To continue, Google will share your name, email address, and language preference with ' + esc(BRAND.name) + '.</p>' +
      '<button class="btn btn-ghost btn-block btn-sm" data-act="sheet-close" style="margin-top:10px">Cancel</button>' +
      '</div>';
    openSheet(html);
  }
  window.signInWithGoogle = signInWithGoogle;

  // --------------------------------------------------------------- events
  function rerender() { render(true); }
  function onClick(e) {
    var hrefEl = e.target.closest("[data-href]");
    var el = e.target.closest("[data-act]");
    if (!el && hrefEl && !e.target.closest("a,button")) { go(hrefEl.getAttribute("data-href")); return; }
    if (!el) return;
    var act = el.getAttribute("data-act"), id = el.getAttribute("data-id");
    switch (act) {
      case "go": go(el.getAttribute("data-to")); break;
      case "back": if (history.length > 1) history.back(); else go(store.onboarded ? "#home" : "#welcome"); break;
      case "google-signin": signInWithGoogle(undefined, el); break;
      case "copy-app-link": {
        var appUrl = appLink(location);
        var copied = function () { toast("Link copied ✓ Paste it in Chrome or Safari"); };
        var selectCopy = function () {
          var inp = $("#iab-link"), okCopy = false;
          if (inp) { inp.focus(); inp.select(); try { inp.setSelectionRange(0, appUrl.length); } catch (err) { /* ignore */ } }
          try { okCopy = document.execCommand("copy"); } catch (err) { /* ignore */ }
          if (okCopy) copied(); else toast("Press and hold the link above to copy it");
        };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(appUrl).then(copied, selectCopy);
        else selectCopy();
        break;
      }
      case "install-dismiss": installHintLive = false; var ih = $("#install-hint"); if (ih) ih.remove(); break;
      case "install-app": {
        var pr = installPrompt; installPrompt = null; installHintLive = false;
        var ihb = $("#install-hint"); if (ihb) ihb.remove();
        if (pr && pr.prompt) { pr.prompt(); if (pr.userChoice) pr.userChoice.then(function (c) { if (c && c.outcome === "accepted") toast("Added to your home screen ✓"); }); }
        break;
      }
      case "pick-google-account": {
        var gName = el.getAttribute("data-name");
        var gEmail = el.getAttribute("data-email");
        closeSheet();
        signInWithGoogle({ name: gName, email: gEmail });
        break;
      }
      case "pick-google-another": {
        closeSheet();
        var entered = prompt("Enter Google account email:", "sweta.demo@gmail.com");
        if (entered && entered.trim()) {
          var cleanEmail = entered.trim();
          var rawName = cleanEmail.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, function (l) { return l.toUpperCase(); });
          signInWithGoogle({ name: rawName, email: cleanEmail });
        }
        break;
      }
      case "start-phone-onboard":
        store.authMethod = "phone"; save(); go("#onboard/city"); break;
      case "skip-onboarding": store.onboarded = true; save(); go("#home"); break;
      case "city-continue": { var ci = $("#city-input"); saveCity(ci ? ci.value : ""); go("#onboard/about"); break; }
      case "city-skip": saveCity(""); go("#onboard/about"); break;
      // Gate card and Me sheet both save through here; re-render opens the real
      // meetups / nearby view straight away once a city is set.
      case "save-city": {
        var src = $("#" + el.getAttribute("data-src"));
        var val = cleanCity(src ? src.value : "");
        if (!val) { if (src) src.focus(); toast("Type your city first"); break; }
        saveCity(val, el); closeSheet(); rerender(); toast("City saved · " + val); break;
      }
      case "clear-city": saveCity("", el); closeSheet(); rerender(); toast("City removed · meetups are off until you add one"); break;
      case "edit-city":
        openSheet("<h3>Your city</h3><p class=\"muted\">Optional. Only meetups and Nearby moms use it.</p>" + cityField("sheet-city", "City") +
          '<div class="sheet-list"><button class="btn btn-primary btn-block" data-act="save-city" data-src="sheet-city" id="sheet-city-save">Save</button>' +
          (hasCity() ? '<button class="sheet-item danger" data-act="clear-city" id="sheet-city-clear">' + icon("close") + "<span>Remove city<small>Meetups and Nearby will ask again</small></span></button>" : "") +
          '<button class="sheet-item" data-act="sheet-close">' + icon("close") + "<span>Cancel</span></button></div>");
        var sc = $("#sheet-city"); if (sc) sc.focus();
        break;
      case "toggle-stage": case "toggle-lang": {
        var arr = act === "toggle-stage" ? store.profile.stages : store.profile.langs, v = el.getAttribute("data-v");
        var i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v);
        save(); el.setAttribute("aria-pressed", i < 0); break;
      }
      case "toggle-anon-default":
        store.profile.anonDefault = !store.profile.anonDefault; askDraft.anon = null; save();
        el.setAttribute("aria-checked", store.profile.anonDefault); break;
      case "verify-phone":
        store.authMethod = "phone";
        el.textContent = "Sending…"; el.disabled = true;
        setTimeout(function () { store.verify.phone = true; save(); rerender(); toast("Code 482 913 auto-filled (demo) ✓"); }, 700); break;
      case "finish-onboarding":
        store.onboarded = true; save();
        if (window.Backend && window.Backend.isReal && window.Backend.user) {
           busy(el);
           window.Backend.saveProfile(window.Backend.user.uid, profileDoc()).then(function () {
             go("#home"); toast("Welcome to the circle, " + store.profile.nickname + " 💛");
           }).catch(failToast("save your profile", el));
           break;
        }
        go("#home"); toast("Welcome to the circle, " + store.profile.nickname + " 💛"); break;
      case "react": {
        if (isRealMode()) { reactLive(el); break; }
        var key = el.getAttribute("data-key") + ":" + el.getAttribute("data-r");
        if (store.reacted[key]) delete store.reacted[key]; else store.reacted[key] = true;
        save();
        var on = !!store.reacted[key];
        el.setAttribute("aria-pressed", on);
        var label = el.textContent.replace(/ · \d+$/, "").replace(/^\S+/, "").trim();
        var m = el.textContent.match(/ · (\d+)$/); var n = (m ? +m[1] : 0) + (on ? 1 : -1);
        el.innerHTML = el.querySelector(".e").outerHTML + label + (n > 0 ? " · " + n : "");
        if (on) { el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); }
        break;
      }
      case "join": store.joined[id] = store.joined[id] === false; save(); rerender(); toast(store.joined[id] === false ? "Left circle" : "Joined 💛"); break;
      case "ask-circle": askDraft.circle = (askDraft.circle === id ? null : id); askDraft.nudge = null; rerender(); break;
      case "ask-anon": askDraft.anon = !askDraft.anon; rerender(); break;
      case "ask-demo":
        if (!askDraft.circle) askDraft.circle = "toddlers";
        askDraft.title = askDraft.title || "Screen time for toddlers — what's normal?";
        askDraft.body = D.kindness.demoAsk; askDraft.nudge = kindnessScan(askDraft.body); rerender();
        setTimeout(function () { var n = $("#ask-nudge"); if (n) n.scrollIntoView({ behavior: "smooth", block: "center" }); }, 50); break;
      case "ask-post": {
        if (!askDraft.title || askDraft.title.trim().length <= 4) break;
        var textToScan = askDraft.title + " " + askDraft.body;
        if (worryingScan(textToScan) && !askDraft.skipWorry) {
           showSafetySheet("ask-post-worry-skip");
           break;
        }
        var hits = kindnessScan(textToScan);
        if (hits.length && !askDraft.skipKind) { askDraft.nudge = hits; rerender(); setTimeout(function () { var n = $("#ask-nudge"); if (n) n.scrollIntoView({ behavior: "smooth", block: "center" }); }, 50); break; }
        var isAnon = !!askDraft.anon;
        var authorName = isAnon ? null : store.profile.nickname;
        var stages = store.profile.stages || [];
        var meta = stages.length ? "Mom · " + stages.join(", ") : "Mom";
        var cId = askDraft.circle || null;
        var cObj = cId ? circle(cId) : null;
        var cn = cObj ? cObj.name : "the circle";
        
        if (window.Backend && window.Backend.isReal) {
          if (!window.Backend.user) { toast("Please sign in to post"); go("#welcome"); break; }
          if (askDraft.saving) break;
          askDraft.saving = true; busy(el);
          window.Backend.addPost(window.Backend.user.uid, authorName, isAnon, cId, askDraft.title.trim(), askDraft.body.trim(), meta, D.me.hue).then(function(docRef) {
            askDraft = { circle: null, title: "", body: "", anon: null, nudge: null };
            go("#q/" + docRef.id); toast("Posted to " + cn + " 💛");
          }).catch(function (e) { askDraft.saving = false; failToast("post", el)(e); });
          break;
        }

        var p = { id: "u" + Date.now(), circle: cId, anon: isAnon, author: authorName, hue: D.me.hue,
          meta: meta, time: "now", title: askDraft.title.trim(), body: askDraft.body.trim(),
          reactions: { hug: 0, been: 0, helpful: 0 }, answers: [] };
        store.posts.unshift(p); save();
        askDraft = { circle: null, title: "", body: "", anon: null, nudge: null };
        go("#q/" + p.id); toast("Posted to " + cn + " 💛"); break;
      }
      case "kind-use": {
        var scope = el.getAttribute("data-scope");
        if (scope === "ask") { askDraft.title = softenText(askDraft.title, kindnessScan(askDraft.title)); askDraft.body = softenText(askDraft.body, askDraft.nudge); askDraft.nudge = null; }
        else { replyDraft.text = softenText(replyDraft.text, replyDraft.nudge); replyDraft.nudge = null; }
        rerender(); toast("Thank you for keeping it kind 💛"); break;
      }
      case "kind-edit": {
        var sc = el.getAttribute("data-scope");
        if (sc === "ask") { askDraft.nudge = null; rerender(); $("#ask-body").focus(); } else { replyDraft.nudge = null; rerender(); $("#reply-text").focus(); }
        break;
      }
      case "kind-skip": {
        var s2 = el.getAttribute("data-scope");
        if (s2 === "ask") { askDraft.skipKind = true; askDraft.nudge = null; onClick({ target: $("#ask-post") }); askDraft.skipKind = false; }
        else { replyDraft.skipKind = true; replyDraft.nudge = null; onClick({ target: $("#reply-send") }); replyDraft.skipKind = false; }
        break;
      }
      case "reply-anon": replyDraft.anon = !replyDraft.anon; rerender(); break;
      case "reply-demo": replyDraft.text = D.kindness.demo; replyDraft.nudge = kindnessScan(replyDraft.text); rerender();
        setTimeout(function () { var s = $("#screen"); s.scrollTop = s.scrollHeight; }, 30); break;
      case "reply-send": {
        var txt = replyDraft.text.trim();
        if (!txt) { $("#reply-text").focus(); break; }
        if (worryingScan(txt) && !replyDraft.skipWorry) {
           showSafetySheet("reply-send-worry-skip");
           break;
        }
        var rh = kindnessScan(txt);
        if (rh.length && !replyDraft.skipKind) { replyDraft.nudge = rh; rerender(); setTimeout(function () { var s = $("#screen"); s.scrollTop = s.scrollHeight; }, 30); break; }
        var pid = replyDraft.pid;
        if (window.Backend && window.Backend.isReal) {
          // Real mode previously wrote replies to localStorage only, so nobody else
          // ever saw them. Now they go to Firestore and the listener re-renders.
          if (!window.Backend.user) { toast("Please sign in to reply"); go("#welcome"); break; }
          if (replyDraft.saving) break;
          replyDraft.saving = true; busy(el);
          var rAnon = !!replyDraft.anon;
          window.Backend.addReply(pid, window.Backend.user.uid, rAnon ? null : store.profile.nickname, rAnon, txt, D.me.hue).then(function () {
            replyDraft.saving = false; replyDraft.text = ""; replyDraft.nudge = null; rerender();
            setTimeout(function () { var s = $("#screen"); s.scrollTop = s.scrollHeight; }, 30);
            toast("Reply posted 💛");
          }).catch(function (e) { replyDraft.saving = false; failToast("post your reply", el)(e); });
          break;
        }
        (store.answers[pid] = store.answers[pid] || []).push({ id: "ua" + Date.now(), anon: replyDraft.anon, author: replyDraft.anon ? null : store.profile.nickname, hue: D.me.hue, time: "now", body: txt, reactions: {} });
        save(); replyDraft.text = ""; replyDraft.nudge = null; rerender();
        setTimeout(function () { var s = $("#screen"); s.scrollTop = s.scrollHeight; }, 30);
        toast("Reply posted 💛"); break;
      }
      case "post-menu": {
        var pp = post(id);
        reportSheet({ title: "Report or block", subject: "this post", postId: id, author: pp.anon ? null : pp.author, name: pp.anon ? null : pp.author });
        break;
      }
      case "answer-menu": {
        var au = el.getAttribute("data-author");
        reportSheet({ title: "Report or block", subject: "this reply", author: au || null }); break;
      }
      case "mom-menu": { var mm = mom(id); reportSheet({ title: mm.nickname, subject: "this profile", momId: id, name: mm.nickname }); break; }
      case "chat-menu": { var cm = mom(id); reportSheet({ title: "Chat with " + cm.nickname, subject: "this conversation", momId: id, name: cm.nickname }); break; }
      case "ask-post-worry-skip":
        askDraft.skipWorry = true;
        closeSheet();
        onClick({ target: $("#ask-post") });
        askDraft.skipWorry = false;
        break;
      case "reply-send-worry-skip":
        replyDraft.skipWorry = true;
        closeSheet();
        onClick({ target: $("#reply-send") });
        replyDraft.skipWorry = false;
        break;
      case "sheet-close-then-safety":
        closeSheet();
        go("#safety");
        break;
      case "sheet-close": closeSheet(); break;
      case "feedback": closeSheet(); openFeedback(); break;
      case "fb-kind": {
        var fk = el.getAttribute("data-v");
        fbDraft.kind = fbDraft.kind === fk ? null : fk;
        Array.prototype.forEach.call(document.querySelectorAll('#fb-sheet [data-act="fb-kind"]'), function (c) { c.setAttribute("aria-pressed", String(c.getAttribute("data-v") === fbDraft.kind)); });
        break;
      }
      case "fb-contact": fbDraft.contactOk = !fbDraft.contactOk; el.setAttribute("aria-checked", String(fbDraft.contactOk)); break;
      case "fb-send": sendFeedback(el); break;
      case "report-start": {
        var lbl = el.getAttribute("data-label");
        var reasons = ["Unkind or shaming", "Harassment or bullying", "Unsafe advice", "Spam or selling", "Not a mom / fake profile", "Something else"];
        openSheet("<h3>Why are you reporting " + esc(lbl) + '?</h3><p class="muted">They won\'t know it was you.</p><div class="sheet-list">' +
          reasons.map(function (r) { return '<button class="sheet-item" data-act="report-done">' + icon("flag") + "<span>" + r + "</span></button>"; }).join("") + "</div>");
        break;
      }
      case "report-done":
        if (window.Backend && window.Backend.isReal && window.Backend.user) {
           var reason = (el.textContent || "reported").trim();
           busy(el);
           window.Backend.addReport(document.getElementById("sheet").getAttribute("data-pid") || "unknown", reason, window.Backend.user.uid).then(function () {
             closeSheet(); toast("Thanks — a moderator will review within 24h");
           }).catch(failToast("send your report", el));
           break;
        }
        // Demo mode: keep the report on this device so Moderation (demo) can show it.
        store.reports = store.reports || [];
        store.reports.unshift({ id: "r" + Date.now(), postId: document.getElementById("sheet").getAttribute("data-pid") || "unknown",
          reason: (el.textContent || "reported").trim(), createdAt: Date.now() });
        save(); closeSheet(); toast("Thanks — a moderator will review within 24h"); break;
      case "mod-remove": {
        var rpid = el.getAttribute("data-pid");
        if (!window.confirm("Remove this post for everyone? Its replies and reports will be deleted too.")) break;
        if (isRealMode()) {
          busy(el);
          window.Backend.removePost(rpid).then(function () { toast("Post removed"); })
            .catch(failToast("remove the post", el));
          break;
        }
        store.posts = store.posts.filter(function (p) { return p.id !== rpid; });
        if (store.hidden.indexOf(rpid) < 0) store.hidden.push(rpid); // built-in demo posts can only be hidden
        store.reports = (store.reports || []).filter(function (r) { return r.postId !== rpid; });
        save(); rerender(); toast("Post removed"); break;
      }
      case "mod-keep": {
        if (!window.confirm("Keep this post and dismiss the report?")) break;
        if (isRealMode()) {
          busy(el);
          window.Backend.deleteReport(id).then(function () { toast("Report dismissed — post kept"); })
            .catch(failToast("dismiss the report", el));
          break;
        }
        store.reports = (store.reports || []).filter(function (r) { return r.id !== id; });
        save(); rerender(); toast("Report dismissed — post kept"); break;
      }
      case "copy-uid": {
        var myUid = (window.Backend && window.Backend.user) ? window.Backend.user.uid : "";
        if (!myUid) break;
        var askCopy = function () { window.prompt("Copy your account ID:", myUid); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(myUid).then(function () { toast("Account ID copied"); }).catch(askCopy);
        } else askCopy();
        break;
      }
      case "sign-out":
        if (window.Backend && window.Backend.isReal) {
           window.Backend.signOut().then(function() {
             localStorage.removeItem(STORE_KEY); store = freshStore();
             go("#welcome"); toast("Signed out");
           }).catch(failToast("sign you out", null));
        }
        break;
      case "hide-post": store.hidden.push(id); save(); closeSheet(); go("#home"); toast("Post hidden"); break;
      case "block": {
        var who = el.getAttribute("data-who"), nm = el.getAttribute("data-name");
        if (store.blocked.indexOf(who) < 0) store.blocked.push(who);
        save(); closeSheet(); rerender(); toast(nm + " is blocked"); break;
      }
      case "blocked-list": {
        var bl = store.blocked.map(function (b) { var bm = mom(b); var n2 = bm ? bm.nickname : b;
          return '<button class="sheet-item" data-act="unblock" data-who="' + esc(b) + '">' + avatar(n2, bm ? bm.hue : "plum", "sm") + "<span>" + esc(n2) + "<small>Tap to unblock</small></span></button>"; }).join("");
        openSheet('<h3>Blocked moms</h3><p class="muted">Blocked moms can\'t see you, message you, or reply to you.</p><div class="sheet-list">' + (bl || '<p class="tiny" style="padding:10px 4px">No one blocked. 🌿</p>') + '<button class="sheet-item" data-act="sheet-close">' + icon("close") + "<span>Close</span></button></div>");
        break;
      }
      case "unblock": store.blocked.splice(store.blocked.indexOf(el.getAttribute("data-who")), 1); save(); closeSheet(); rerender(); toast("Unblocked"); break;
      case "guidelines":
        openSheet('<h3>Our promise to each other</h3><div class="sheet-list" style="gap:10px;font-size:14px">' +
          ["💛 Assume every mom is doing her best.", "🙅🏽‍♀️ No shaming — feeding, sleep, work, culture or choices.", "🔒 What's shared here stays here.", "🩺 Advice isn't a diagnosis. Experts are badged.", "🚩 Report anything that feels off. We act within 24h."].map(function (g) { return '<div class="card" style="padding:12px 14px">' + g + "</div>"; }).join("") +
          '<button class="btn btn-primary btn-block" data-act="sheet-close" style="margin-top:6px">I promise</button></div>');
        break;
      case "nearby-on": store.nearbyOn = true; save(); render(); toast("You're visible at neighbourhood level only"); break;
      case "nearby-toggle": store.nearbyOn = !store.nearbyOn; save(); el.setAttribute("aria-checked", store.nearbyOn); toast(store.nearbyOn ? "Visible to nearby moms (neighbourhood only)" : "You're hidden from Nearby"); break;
      case "hood": nearbyFilter = nearbyFilter === id ? null : id; rerender(); break;
      case "hood-clear": nearbyFilter = null; rerender(); break;
      case "say-hi": {
        var sm = mom(id);
        store.req[id] = "pending"; save(); rerender(); toast("Hi sent to " + sm.nickname + " 👋");
        // Mock the other mom accepting a moment later so the unlock is demoable.
        setTimeout(function () {
          store.req[id] = "accepted"; save();
          if (parseHash().name === "nearby") rerender();
          toast(sm.nickname + " said hi back — chat unlocked 🎉");
        }, 2600);
        break;
      }
      case "rsvp": store.rsvp[id] = !store.rsvp[id]; save(); rerender(); toast(store.rsvp[id] ? "You're going! We'll remind you the day before 🌼" : "RSVP removed"); break;
      case "seg": meetupsSeg = el.getAttribute("data-v"); rerender(); break;
      case "policy": store.msgPolicy = el.getAttribute("data-v"); save(); rerender(); break;
      case "chat-send": {
        var ta = $("#chat-text"), t = ta.value.trim();
        if (!t) { ta.focus(); break; }
        var now = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        store.chats[id].push({ from: "me", text: t, time: now }); save(); render(true);
        var msgsEl = $("#msgs");
        msgsEl.insertAdjacentHTML("beforeend", '<div class="typing" id="typing"><i></i><i></i><i></i></div>');
        $("#screen").scrollTop = $("#screen").scrollHeight;
        setTimeout(function () {
          store.chats[id].push({ from: "them", text: MOCK_REPLIES[store.chats[id].length % MOCK_REPLIES.length], time: now }); save();
          if (parseHash().name === "chat") render(true);
          var s = $("#screen"); s.scrollTop = s.scrollHeight;
        }, 1400);
        break;
      }
      case "soon": toast("Coming soon in the real app ✨"); break;
      case "reset": localStorage.removeItem(STORE_KEY); store = freshStore(); askDraft = { circle: null, title: "", body: "", anon: null, nudge: null }; go("#welcome"); toast("Demo reset"); break;
    }
  }
  function onInput(e) {
    var k = e.target.getAttribute("data-input");
    if (!k) return;
    var v = e.target.value;
    if (k === "nick") {
      store.profile.nickname = v.trim() ? v.trim() : ""; save();
      var b = $("#about-continue"); if (b) b.disabled = !v.trim();
    } else if (k === "ask-title" || k === "ask-body") {
      askDraft[k === "ask-title" ? "title" : "body"] = v;
      var canPost = askDraft.title.trim().length > 4;
      var bt = $("#ask-post"); if (bt) bt.disabled = !canPost;
      var hint = $("#ask-hint"); if (hint) hint.style.display = canPost ? "none" : "";
    } else if (k === "fb-text") {
      fbDraft.text = v.slice(0, FEEDBACK_MAX);
      var fc = $("#fb-count"); if (fc) fc.textContent = fbDraft.text.length + " / " + FEEDBACK_MAX;
      var fs = $("#fb-send"); if (fs && !fbDraft.sending) fs.disabled = !fbDraft.text.trim();
    } else if (k === "reply-text") {
      replyDraft.text = v;
      e.target.style.height = "auto"; e.target.style.height = Math.min(120, e.target.scrollHeight) + "px";
    }
  }
  function onKey(e) {
    if (e.key === "Escape") closeSheet();
    if (e.key === "Enter" && !e.shiftKey && e.target.id === "chat-text") { e.preventDefault(); $("#chat-send").click(); }
    if (e.key === "Enter" && e.target.getAttribute && e.target.getAttribute("data-city-input")) {
      e.preventDefault();
      var cbtn = e.target.id === "city-input" ? $("#city-continue") : $('[data-act="save-city"][data-src="' + e.target.id + '"]');
      if (cbtn) cbtn.click();
    }
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("g.hood")) { e.preventDefault(); onClick({ target: e.target }); }
  }

  function showcase() {
    var links = [["#welcome", "Welcome"], ["#onboard/city", "City picker"], ["#onboard/about", "About you"], ["#onboard/verify", "Verification"], ["#home", "Home feed"],
      ["#ask", "Ask"], ["#q/p1", "Question + expert"], ["#nearby", "Nearby moms"], ["#meetups", "Meetups"], ["#chat/m1", "Chat"], ["#me", "Profile & privacy"]];
    var sc = $("#showcase");
    if (sc) sc.innerHTML = '<div class="sc-logo">' + logoMark() + '<span class="logo-word">' + esc(BRAND.name) + "</span></div>" +
      "<h2>" + esc(BRAND.tagline) + "</h2><p>" + esc(BRAND.blurb) + "</p>" +
      '<div class="sc-links">' + links.map(function (l) { return '<a href="' + l[0] + '">' + l[1] + "</a>"; }).join("") + "</div>" +
      "<small>" + (isRealMode() ? esc(BRAND.name) + " · v0.1 · beta" : "Clickable prototype · mock data only · all people are fictional") + "</small>";
  }

  // "Demo mode" badge. Shown ONLY once Backend.ready has resolved with isReal
  // false: Backend.isReal is false while the Firebase SDK is still loading, so
  // checking it at DOMContentLoaded labelled real mode as demo.
  function showDemoLabel() {
    if (document.getElementById("demo-label")) return;
    var d = document.createElement("div");
    d.id = "demo-label";
    d.innerHTML = "Demo mode";
    d.style = "position:fixed;bottom:env(safe-area-inset-bottom, 5px);right:5px;font-size:10px;background:rgba(0,0,0,0.5);color:#fff;padding:2px 6px;border-radius:4px;z-index:9999;pointer-events:none;";
    document.body.appendChild(d);
  }

  // Firestore listeners. Rules require sign-in to read, and an onSnapshot error
  // kills the listener permanently, so we (re)subscribe on every sign-in and tear
  // down on sign-out instead of subscribing once at load.
  //
  // Self-healing (2026-10-09, "the other mom has to reload to see a new post"):
  // an onSnapshot error used to just show a toast, leaving the feed frozen until a
  // reload. Now a failed listener is marked dead and re-attached once after a
  // backoff (2s, 4s ... 60s), and immediately when the tab becomes visible again or
  // the browser comes back online. This is NOT polling: while a listener is healthy
  // nothing runs; Firestore pushes changes over its one open stream.
  var live = { postsDead: false, repliesDead: false, marksDead: false, retry: 0, timer: null, postsSig: null, repliesSig: null };
  // quiet: no toast (her markers only drive pressed state; the cache covers a miss).
  function healListener(kind, what, quiet) {
    return function (e) {
      var B = window.Backend;
      if (kind === "posts") { B._unsubPosts = null; live.postsDead = true; }
      else if (kind === "marks") { B._unsubMarks = null; live.marksDead = true; }
      else { B._unsubReplies = null; live.repliesDead = true; }
      if (live.retry === 0 && !quiet) failToast(what, null)(e);
      else console.error("MomSakhi: listener failed again (" + kind + ")", e);
      var wait = Math.min(60000, 2000 * Math.pow(2, live.retry++));
      clearTimeout(live.timer);
      live.timer = setTimeout(reviveListeners, wait);
    };
  }
  function reviveListeners() {
    var B = window.Backend;
    if (!B || !B.isReal || !B.user) return;
    if (live.postsDead) syncPosts();
    if (live.repliesDead) syncReplies();
    if (live.marksDead) syncMarks();
  }
  // Snapshot "shape" minus reaction counts: equal before/after means only
  // reactions moved, so patchReactions() is enough and nothing re-renders.
  function contentSig(list) {
    try {
      return JSON.stringify((list || []).map(function (d) {
        var c = {}; for (var k in d) if (k !== "reactions" && k !== "time") c[k] = d[k]; return c;
      }));
    } catch (e) { return "x" + Math.random(); }
  }
  function syncReplies() {
    var B = window.Backend;
    if (!B || !B.isReal) return;
    var r = parseHash();
    if (B._unsubReplies) { B._unsubReplies(); B._unsubReplies = null; }
    B._currentReplies = [];
    live.repliesDead = false;
    live.repliesSig = null;
    if (r.name !== "q" || !r.arg || !B.user) return;
    B._unsubReplies = B.listenReplies(r.arg, function(reps) {
      live.retry = 0;
      var sig = contentSig(reps), same = sig === live.repliesSig;
      live.repliesSig = sig;
      B._currentReplies = reps;
      if (parseHash().name === "q" && parseHash().arg === r.arg) { if (same) patchReactions(); else rerender(); }
    }, healListener("replies", "load replies"));
  }
  // Her own reaction markers (pressed state on every device). Re-attached on every
  // auth change; resetReactions() drops the previous mom's state first.
  function resetReactions() { reactState.mine = null; reactState.pending = {}; }
  function syncMarks() {
    var B = window.Backend;
    if (B._unsubMarks) { B._unsubMarks(); B._unsubMarks = null; }
    live.marksDead = false;
    if (!B.user || !B.listenMyReactions) return;
    var uid = B.user.uid;
    B._unsubMarks = B.listenMyReactions(uid, function (mine) {
      live.retry = 0;
      if (!B.user || B.user.uid !== uid) return;
      reactState.mine = mine;
      store.reactedLive = Object.assign({}, mine); store.reactedLiveUid = uid; save();
      patchReactions();
    }, healListener("marks", "load your reactions", true));
  }
  // Tap on a reaction in real mode. One write per button at a time (double taps
  // while it is in flight are ignored); the button flips at once (optimistic),
  // Firestore's latency compensation moves the count at once, and a denied or
  // failed write flips both back and tells her why.
  function reactLive(el) {
    var B = window.Backend;
    var bk = el.getAttribute("data-key"), r = el.getAttribute("data-r"), k = bk + ":" + r;
    if (!B.user || !B.setReaction) { toast("Sign in with Google to react 💛"); return; }
    if (reactState.pending[k] !== undefined) return;
    var want = !isReacted(k), uid = B.user.uid;
    var i = bk.indexOf("/"), pid = i < 0 ? bk : bk.slice(0, i), rid = i < 0 ? null : bk.slice(i + 1);
    function cache(v) {
      if (store.reactedLiveUid !== uid) { store.reactedLive = {}; store.reactedLiveUid = uid; }
      if (v) store.reactedLive[k] = true; else delete store.reactedLive[k];
      save();
    }
    reactState.pending[k] = want; cache(want); patchReactions();
    if (want) { el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); }
    var done = false;
    B.setReaction(uid, pid, rid, r, want).then(function () {
      done = true; delete reactState.pending[k]; patchReactions();
    }, function (e) {
      if (done) return;
      delete reactState.pending[k]; cache(!want);
      if (reactState.mine) { if (want) delete reactState.mine[k]; else reactState.mine[k] = true; }
      patchReactions();
      failToast("save your reaction", null)(e);
    });
  }
  // Re-evaluated on every auth change: drop the old listener/flag first so a
  // signed-out or different user never sees the previous moderator's queue.
  // A failed check (e.g. rules not yet published) just means "not a moderator".
  function syncModerator(u) {
    var B = window.Backend;
    if (modState.unsub) { modState.unsub(); modState.unsub = null; }
    if (modState.unsubFb) { modState.unsubFb(); modState.unsubFb = null; }
    modState.isMod = false; modState.reports = []; modState.postCache = {}; modState.fetching = {}; modState.feedback = [];
    if (!u || !B || !B.checkModerator) return;
    B.checkModerator(u.uid).then(function (isMod) {
      if (!isMod || !B.user || B.user.uid !== u.uid) return;
      modState.isMod = true;
      modState.unsub = B.listenReports(function (reps) {
        modState.reports = reps;
        var n = parseHash().name; if (n === "mod" || n === "me") rerender();
      }, failToast("load reports", null));
      if (B.listenFeedback) modState.unsubFb = B.listenFeedback(function (items) {
        modState.feedback = items;
        if (parseHash().name === "mod") rerender();
      }, function (e) { console.warn("MomSakhi: couldn't load feedback (rules not published yet?)", e); });
      var n2 = parseHash().name; if (n2 === "mod" || n2 === "me") rerender();
    }).catch(function (e) { console.warn("MomSakhi: moderator check failed (treated as not a moderator)", e); });
  }
  function syncPosts() {
    var B = window.Backend;
    if (B._unsubPosts) { B._unsubPosts(); B._unsubPosts = null; }
    live.postsDead = false;
    live.postsSig = null;
    if (!B.user) { B.posts = []; return; }
    B._unsubPosts = B.listenPosts("all", function(posts) {
      live.retry = 0;
      var r = parseHash();
      var had = r.name === "q" && (B.posts || []).some(function (p) { return p.id === r.arg; });
      var sig = contentSig(posts), same = sig === live.postsSig;
      live.postsSig = sig;
      B.posts = posts;
      // On #q only re-render when the post first shows up (direct link / just
      // posted); otherwise a feed update would wipe focus while she types a reply.
      // A reactions-only change (same sig) never re-renders: patchReactions().
      if ((r.name === "home" || r.name === "circle") && !same) rerender();
      else if (r.name === "q" && !had) rerender();
      else patchReactions();
    }, healListener("posts", "load posts"));
  }

  document.addEventListener("DOMContentLoaded", function () {
    var app = $("#app");
    app.addEventListener("click", onClick);
    app.addEventListener("input", onInput);
    document.addEventListener("keydown", onKey);
    window.addEventListener("online", reviveListeners);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) reviveListeners(); });
    $("#sheet-backdrop").addEventListener("click", closeSheet);
    window.addEventListener("hashchange", function () { 
      closeSheet(); 
      syncReplies();
      render(); 
    });
    showcase();
    // Installable app: register the shell-only worker (relative URL + scope so it
    // works under /momsakhi/ on Pages and at / on localhost) and keep Chrome's
    // install prompt for the Home hint instead of its default mini-infobar.
    if ("serviceWorker" in navigator && /^https?:$/.test(location.protocol)) {
      navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(function (e) {
        console.warn("MomSakhi: service worker not registered", e);
      });
    }
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      installPrompt = e;
      if (parseHash().name === "home" && !$("#install-hint")) rerender();
    });
    window.addEventListener("appinstalled", function () {
      installPrompt = null; installHintLive = false;
      var ih = $("#install-hint"); if (ih) ih.remove();
    });
    if (window.Backend && window.Backend.ready) {
      window.Backend.ready.then(function() {
        if (window.Backend.isReal) {
          showcase();
          // Coming back from a signInWithRedirect fallback: finish sign-in here.
          window.Backend.getRedirectResult().then(function (result) {
            if (result && result.user) return afterGoogleSignIn(result.user);
          }).catch(function (e) {
            if (isWebviewAuthError(e)) { showSignInBlocked(); return; }
            failToast("sign you in", null)(e);
          });
          window.Backend.onAuth(function(u) {
            window.Backend.user = u;
            resetReactions();
            syncPosts();
            syncReplies();
            syncMarks();
            syncModerator(u);
            if (u) {
               window.Backend.getProfile(u.uid).then(function(p) {
                 if (p) { applyProfile(p); store.onboarded = true; save(); }
                 render();
               }).catch(function (e) {
                 failToast("load your profile", null)(e);
                 render();
               });
            } else {
               render();
            }
          });
        } else {
          showDemoLabel();
          render();
        }
      });
    } else {
      showDemoLabel();
      render();
    }
  });

  // Exposed for tests/screenshot tooling only.
  window.AANGAN = { kindnessScan: kindnessScan, softenText: softenText, reset: function () { localStorage.removeItem(STORE_KEY); },
    syncModerator: syncModerator, V: V, isRealMode: isRealMode, cleanCity: cleanCity, saveCity: saveCity,
    inAppBrowser: inAppBrowser, isWebviewAuthError: isWebviewAuthError, appLink: appLink, chromeIntentUrl: chromeIntentUrl,
    showSignInBlocked: showSignInBlocked,
    city: function () { return store.city; } };
})();
