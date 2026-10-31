// web/backend.js
// Thin wrapper over Firebase (Auth + Firestore). When window.FIREBASE_CONFIG is
// filled in, Backend.ready resolves with isReal = true and every hook below talks
// to Firestore; otherwise (or if the SDK fails to load) the app stays in demo mode.
//
// Design notes (2026-10-08 hardening):
// - Every write returns the raw Firebase promise so app.js can .catch it and show
//   the mom a toast; nothing here swallows errors silently.
// - Firestore addDoc/setDoc REJECT documents containing `undefined`, so every
//   field is coerced to a safe default before writing (anon is always a boolean).
// - Popup sign-in is blocked on many mobile browsers / in-app webviews, so a few
//   specific popup failures fall back to signInWithRedirect; app.js picks the
//   result up on the next load via Backend.getRedirectResult().
// - replyCount is bumped with increment(1) AFTER the reply is written. It is a
//   best-effort counter: a failed bump never fails the reply itself.
// - Snapshot listeners take an error callback; an onSnapshot error ends the
//   listener for good, so app.js only starts listening once a user is signed in
//   (rules require auth for reads) and re-subscribes after the next sign-in.
(function() {
  window.Backend = {
    isReal: false,
    ready: null,
    user: null,
    // hooks
    signInWithGoogle: null,
    getRedirectResult: null,
    signOut: null,
    onAuth: null,
    getProfile: null,
    saveProfile: null,
    addPost: null,
    addReply: null,
    addReport: null,
    listenPosts: null,
    listenReplies: null,
    checkModerator: null,
    listenReports: null,
    deleteReport: null,
    getPost: null,
    removePost: null,
    setReaction: null,
    listenMyReactions: null,
    addFeedback: null,
    listenFeedback: null,
    checkMember: null,
    getInvite: null,
    redeemInvite: null,
    createInvite: null,
    listenInvites: null,
    disableInvite: null,
    deleteInvite: null,
    updateInviteSeats: null,
    requestInvite: null,
    listenWaitlist: null,
    deleteWaitlist: null,
    listenMembers: null,
    listenProfiles: null
  };

  // Popup failures that mean "this browser can't do popups", not "the mom said no".
  // 2026-10-27: Removed REDIRECT_FALLBACK_CODES. Cross-origin redirect is dead
  // on modern mobile browsers due to 3rd-party cookie blocking. Let errors bubble
  // up to app.js instead so the webview warning card can be shown.

  function str(v, fallback) { return (typeof v === "string") ? v : (v == null ? fallback : String(v)); }
  // JSON round-trip drops undefined values (Firestore rejects them) and functions.
  function plain(obj) { return JSON.parse(JSON.stringify(obj || {})); }
  // Pure so tests can call it with fake location objects (Backend._useEmulators).
  function useEmulators(loc) {
    if (!loc) return false;
    var host = loc.hostname;
    if (host !== "localhost" && host !== "127.0.0.1") return false;
    return /(^\?|&)emu=1(&|$)/.test(loc.search || "");
  }
  Backend._useEmulators = useEmulators;

  // ---- Post / reply payloads (pure, so tests can call them without Firebase).
  // 2026-10-12 anonymity fix: an ANONYMOUS post or reply carries NO uid (and no
  // other per-mom id) in the publicly readable doc -- otherwise any signed-in mom
  // could link "Anonymous mom" posts to the same account's named posts. Who wrote
  // it lives only in the moderator-only /postAuthors record (see authorRecord and
  // firestore.rules). Named posts keep uid, as before. `ts` is serverTimestamp().
  function postPayload(uid, authorName, isAnon, circle, title, body, meta, hue, intent, ts, photo) {
    var anon = !!isAnon;
    var data = {
      author: anon ? null : str(authorName, "Mom"),
      anon: anon,
      circle: (circle && typeof circle === "string" && circle.trim()) ? circle.trim() : null,
      title: str(title, ""),
      body: str(body, ""),
      meta: str(meta, "Mom"),
      hue: str(hue, "teal"),
      createdAt: ts,
      replyCount: 0
    };
    if (!anon) data.uid = uid;
    // Post type: "advice" is a Question, "vent" a Vent, "experience" an Experience
    // (shown in the Moms' tips feed). No intent = an untyped post, read as a Question.
    if (intent === "vent" || intent === "advice" || intent === "experience") data.intent = intent;
    // 2026-10-31 fix: an attached photo was never written (it only lived on the
    // optimistic local copy, so it vanished on the next snapshot). It now rides
    // on the post as a downscaled JPEG data URL (app.js PHOTO_MAX; rules check it).
    if (typeof photo === "string" && photo.indexOf("data:image/jpeg;base64,") === 0) data.photo = photo;
    return data;
  }
  function replyPayload(uid, authorName, isAnon, body, hue, ts) {
    var anon = !!isAnon;
    var data = {
      author: anon ? null : str(authorName, "Mom"),
      anon: anon,
      body: str(body, ""),
      hue: str(hue, "teal"),
      createdAt: ts
    };
    if (!anon) data.uid = uid;
    return data;
  }
  // The private "who wrote this anonymous post/reply" note: exactly these keys.
  function authorRecord(uid, ts) { return { uid: uid, createdAt: ts }; }
  Backend._postPayload = postPayload;
  Backend._replyPayload = replyPayload;
  Backend._authorRecord = authorRecord;

  if (window.FIREBASE_CONFIG && window.FIREBASE_CONFIG.apiKey && window.FIREBASE_CONFIG.apiKey.indexOf("PASTE") === -1) {
    Backend.ready = Promise.all([
      import("https://www.gstatic.com/firebasejs/10.4.0/firebase-app.js"),
      import("https://www.gstatic.com/firebasejs/10.4.0/firebase-auth.js"),
      import("https://www.gstatic.com/firebasejs/10.4.0/firebase-firestore.js")
    ]).then(function(modules) {
      var app = modules[0].initializeApp(window.FIREBASE_CONFIG);
      var auth = modules[1].getAuth(app);
      var db = modules[2].getFirestore(app);

      // Local test hook: point at the Firebase Local Emulator Suite (fake Google
      // accounts, same firestore.rules) ONLY on localhost/127.0.0.1 AND with ?emu=1.
      // The live site (momsakhi.com) can never satisfy the hostname check.
      if (useEmulators(window.location)) {
        modules[1].connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
        modules[2].connectFirestoreEmulator(db, "127.0.0.1", 8080);
        Backend.usingEmulators = true;
      }

      Backend.isReal = true;
      Backend._auth = auth;
      Backend._db = db;

      var signInWithPopup = modules[1].signInWithPopup;
      var signInWithRedirect = modules[1].signInWithRedirect;
      var fbGetRedirectResult = modules[1].getRedirectResult;
      var GoogleAuthProvider = modules[1].GoogleAuthProvider;
      var fbSignOut = modules[1].signOut;
      var onAuthStateChanged = modules[1].onAuthStateChanged;
      var doc = modules[2].doc, getDoc = modules[2].getDoc, setDoc = modules[2].setDoc,
          updateDoc = modules[2].updateDoc, increment = modules[2].increment,
          collection = modules[2].collection, addDoc = modules[2].addDoc, deleteDoc = modules[2].deleteDoc,
          getDocs = modules[2].getDocs, writeBatch = modules[2].writeBatch, where = modules[2].where,
          serverTimestamp = modules[2].serverTimestamp, query = modules[2].query,
          orderBy = modules[2].orderBy, onSnapshot = modules[2].onSnapshot, limit = modules[2].limit;

      // Resolves with the UserCredential (popup). Rejects for every failure.
      // 2026-10-27: Removed signInWithRedirect fallback. Cross-origin redirect is
      // dead on modern mobile browsers due to 3rd-party cookie blocking, causing
      // silent loops. Instead, let errors bubble up to app.js to show the
      // in-app browser card or instruct the user to retry/allow popups.
      Backend.signInWithGoogle = function() {
        var provider = new GoogleAuthProvider();
        provider.setCustomParameters({ prompt: "select_account" });
        return signInWithPopup(auth, provider);
      };

      // Null when the page wasn't opened by a sign-in redirect.
      Backend.getRedirectResult = function() {
        return fbGetRedirectResult(auth);
      };

      Backend.signOut = function() {
        return fbSignOut(auth);
      };

      Backend.onAuth = function(cb) {
        return onAuthStateChanged(auth, cb);
      };

      Backend.getProfile = function(uid) {
        return getDoc(doc(db, "profiles", uid)).then(function(snap) {
          return snap.exists() ? snap.data() : null;
        });
      };

      Backend.saveProfile = function(uid, profile) {
        return setDoc(doc(db, "profiles", uid), plain(profile), { merge: true });
      };

      // Named posts: one addDoc carrying uid. Anonymous posts: ONE batch writes the
      // uid-free post AND /postAuthors/{postId} {uid}; rules accept each half only
      // alongside the other, so an anon post always has a (private) author record
      // and nobody can claim someone else's post. Resolves with the post's ref.
      Backend.addPost = function(uid, authorName, isAnon, circle, title, body, meta, hue, intent, photo) {
        var data = postPayload(uid, authorName, isAnon, circle, title, body, meta, hue, intent, serverTimestamp(), photo);
        if (!data.anon) return addDoc(collection(db, "posts"), data);
        var postRef = doc(collection(db, "posts"));
        var batch = writeBatch(db);
        batch.set(postRef, data);
        batch.set(doc(db, "postAuthors", postRef.id), authorRecord(uid, serverTimestamp()));
        return batch.commit().then(function() { return postRef; });
      };

      // Same split for replies: anon -> uid-free reply + /postAuthors/{postId}/replies/{replyId}.
      Backend.addReply = function(postId, uid, authorName, isAnon, body, hue) {
        var data = replyPayload(uid, authorName, isAnon, body, hue, serverTimestamp());
        var write;
        if (!data.anon) {
          write = addDoc(collection(db, "posts/" + postId + "/replies"), data);
        } else {
          var replyRef = doc(collection(db, "posts/" + postId + "/replies"));
          var batch = writeBatch(db);
          batch.set(replyRef, data);
          batch.set(doc(db, "postAuthors", postId, "replies", replyRef.id), authorRecord(uid, serverTimestamp()));
          write = batch.commit().then(function() { return replyRef; });
        }
        return write.then(function(ref) {
          // Best-effort counter for the feed; rules only allow +1 on replyCount.
          updateDoc(doc(db, "posts", postId), { replyCount: increment(1) }).catch(function(e) {
            console.warn("replyCount bump failed (reply itself was saved)", e);
          });
          return ref;
        });
      };

      Backend.updatePost = function(postId, title, body) {
        return updateDoc(doc(db, "posts", postId), {
          title: str(title, ""),
          body: str(body, ""),
          editedAt: serverTimestamp()
        });
      };

      Backend.updateReply = function(postId, replyId, body) {
        return updateDoc(doc(db, "posts/" + postId + "/replies", replyId), {
          body: str(body, ""),
          editedAt: serverTimestamp()
        });
      };

      Backend.addReport = function(postId, reason, reporterUid) {
        return addDoc(collection(db, "reports"), {
          postId: str(postId, "unknown"),
          reason: str(reason, "reported"),
          reporterUid: reporterUid,
          createdAt: serverTimestamp()
        });
      };

      // serverTimestamps: "estimate" gives our own just-written docs a local time
      // instead of null while the write is pending, so ordering/labels stay sane.
      Backend.listenPosts = function(circleId, cb, onError) {
        var q = query(collection(db, "posts"), orderBy("createdAt", "desc"), limit(100));
        return onSnapshot(q, function(snap) {
          var posts = [];
          snap.forEach(function(d) {
            var data = d.data({ serverTimestamps: "estimate" });
            data.id = d.id;
            if (circleId && circleId !== "all" && data.circle !== circleId) return;
            posts.push(data);
          });
          cb(posts);
        }, function(e) {
          console.error("listenPosts failed", e);
          if (onError) onError(e);
        });
      };

      Backend.listenReplies = function(postId, cb, onError) {
        var q = query(collection(db, "posts/" + postId + "/replies"), orderBy("createdAt", "asc"));
        return onSnapshot(q, function(snap) {
          var replies = [];
          snap.forEach(function(d) {
            var data = d.data({ serverTimestamps: "estimate" });
            data.id = d.id;
            replies.push(data);
          });
          cb(replies);
        }, function(e) {
          console.error("listenReplies failed", e);
          if (onError) onError(e);
        });
      };

      // ---- Moderation (rules are the real gate; see firestore.rules isModerator()).
      // Resolves true only if /moderators/{uid} exists. Rules let a mom read only her
      // own moderators doc, so this never leaks who the moderators are.
      Backend.checkModerator = function(uid) {
        return getDoc(doc(db, "moderators", uid)).then(function(snap) { return snap.exists(); });
      };

      Backend.listenReports = function(cb, onError) {
        var q = query(collection(db, "reports"), orderBy("createdAt", "desc"));
        return onSnapshot(q, function(snap) {
          var reports = [];
          snap.forEach(function(d) {
            var data = d.data({ serverTimestamps: "estimate" });
            data.id = d.id;
            reports.push(data);
          });
          cb(reports);
        }, function(e) {
          console.error("listenReports failed", e);
          if (onError) onError(e);
        });
      };

      Backend.deleteReport = function(reportId) {
        return deleteDoc(doc(db, "reports", reportId));
      };

      // Null when the post no longer exists (already removed by its author/a moderator).
      Backend.getPost = function(postId) {
        return getDoc(doc(db, "posts", postId)).then(function(snap) {
          if (!snap.exists()) return null;
          var data = snap.data({ serverTimestamps: "estimate" });
          data.id = snap.id;
          return data;
        });
      };

      // Moderator "Remove post". Firestore does not cascade deletes, so the replies,
      // the post itself and every report about it go in ONE batch: all-or-nothing, and
      // rules check each write (a non-moderator gets permission-denied for the lot).
      // A post that is already gone just has its reports cleared. Batches cap at 500
      // writes, far beyond a single post's replies at this community's size.
      Backend.removePost = function(postId) {
        var postRef = doc(db, "posts", postId);
        return Promise.all([
          getDoc(postRef),
          getDocs(collection(db, "posts/" + postId + "/replies")),
          getDocs(query(collection(db, "reports"), where("postId", "==", postId)))
        ]).then(function(res) {
          var batch = writeBatch(db);
          res[1].forEach(function(d) { batch.delete(d.ref); });
          res[2].forEach(function(d) { batch.delete(d.ref); });
          if (res[0].exists()) batch.delete(postRef);
          return batch.commit();
        });
      };

      // ---- Reactions (see the long comment in firestore.rules). One batch writes
      // BOTH her marker /userReactions/{uid}/marks/{markId} and the +-1 on the
      // post's (or reply's) reactions.{r} counter; rules accept each half only
      // alongside the other, so the count can't drift or be stuffed. Firestore's
      // latency compensation fires every listener at once with the pending write
      // (instant feedback) and rolls it back automatically if the commit is denied.
      // markId: "<postId>_<r>" or "<postId>_<replyId>_<r>" (auto ids have no "_").
      Backend.markId = function(postId, replyId, r) {
        return replyId ? postId + "_" + replyId + "_" + r : postId + "_" + r;
      };
      Backend.setReaction = function(uid, postId, replyId, r, on) {
        var markRef = doc(db, "userReactions", uid, "marks", Backend.markId(postId, replyId, r));
        var target = replyId ? doc(db, "posts", postId, "replies", replyId) : doc(db, "posts", postId);
        var batch = writeBatch(db);
        if (on) batch.set(markRef, { post: postId, reply: replyId || null, r: r, at: serverTimestamp() });
        else batch.delete(markRef);
        var bump = {};
        bump["reactions." + r] = increment(on ? 1 : -1);
        batch.update(target, bump);
        return batch.commit();
      };
      // Her own markers -> cb({ "<postId>:<r>" | "<postId>/<replyId>:<r>": true }),
      // the same key shape app.js uses for reaction buttons (data-key + ":" + r).
      Backend.listenMyReactions = function(uid, cb, onError) {
        return onSnapshot(collection(db, "userReactions", uid, "marks"), function(snap) {
          var mine = {};
          snap.forEach(function(d) {
            var m = d.data();
            if (!m || typeof m.post !== "string" || typeof m.r !== "string") return;
            mine[(m.reply ? m.post + "/" + m.reply : m.post) + ":" + m.r] = true;
          });
          cb(mine);
        }, function(e) {
          console.error("listenMyReactions failed", e);
          if (onError) onError(e);
        });
      };
      // ---- Feedback ("💬 Send feedback"). Write-only for moms: rules allow create
      // with exactly these keys and let ONLY moderators read (Firebase console or
      // Me -> Moderation). kind is null when she didn't pick one.
      Backend.addFeedback = function(uid, text, kind, contactOk, page, ua) {
        return addDoc(collection(db, "feedback"), {
          uid: uid,
          text: str(text, ""),
          kind: kind || null,
          contactOk: !!contactOk,
          page: str(page, "").slice(0, 200),
          ua: str(ua, "").slice(0, 300),
          createdAt: serverTimestamp()
        });
      };
      Backend.listenFeedback = function(cb, onError) {
        var q = query(collection(db, "feedback"), orderBy("createdAt", "desc"), limit(100));
        return onSnapshot(q, function(snap) {
          var items = [];
          snap.forEach(function(d) {
            var data = d.data({ serverTimestamps: "estimate" });
            data.id = d.id;
            items.push(data);
          });
          cb(items);
        }, function(e) {
          console.error("listenFeedback failed", e);
          if (onError) onError(e);
        });
      };
      // Test hook (emulator rules checks in the two-user harness); grants nothing
      // beyond what the page could already do -- firestore.rules is the gate.
      Backend._fs = modules[2];

      // ---- Closed beta: invite codes (2026-10-12). firestore.rules is the real
      // gate (isMember()); these are thin calls. Timestamps come back as millis
      // (expiresAtMs / createdAtMs) so app.js never touches Firestore types.
      function inviteData(snap) {
        var d = snap.data({ serverTimestamps: "estimate" }) || {};
        var out = { code: snap.id, maxUses: d.maxUses, uses: d.uses, note: d.note || null, createdBy: d.createdBy };
        out.expiresAtMs = d.expiresAt && d.expiresAt.toMillis ? d.expiresAt.toMillis() : null;
        out.createdAtMs = d.createdAt && d.createdAt.toMillis ? d.createdAt.toMillis() : null;
        return out;
      }
      // True when /members/{uid} exists (rules: she may read only her own).
      Backend.checkMember = function(uid) {
        return getDoc(doc(db, "members", uid)).then(function(snap) { return snap.exists(); });
      };
      // One invite by exact code (rules allow `get`, never `list`, for non-moderators).
      // Null when there is no such code.
      Backend.getInvite = function(code) {
        return getDoc(doc(db, "invites", code)).then(function(snap) { return snap.exists() ? inviteData(snap) : null; });
      };
      // Redemption is ONE batch: her member doc + exactly +1 on the code's uses.
      // Rules accept each half only alongside the other (redeemedWith / redeemBump),
      // and increment(1) is applied server-side, so two moms racing for the last
      // seat can't both get in (the second sees uses == maxUses and is denied).
      Backend.redeemInvite = function(uid, code) {
        var batch = writeBatch(db);
        batch.set(doc(db, "members", uid), { code: code, joinedAt: serverTimestamp() });
        batch.update(doc(db, "invites", code), { uses: increment(1) });
        return batch.commit();
      };
      // Moderators only. setDoc on an existing code would be an update, which rules
      // reject (uses/createdBy may not change), so a collision fails instead of
      // overwriting a live code.
      Backend.createInvite = function(uid, code, maxUses, note, expiresAtMs) {
        var data = { maxUses: maxUses, uses: 0, createdBy: uid, createdAt: serverTimestamp() };
        if (note) data.note = str(note, "").slice(0, 80);
        if (expiresAtMs) data.expiresAt = modules[2].Timestamp.fromMillis(expiresAtMs);
        return setDoc(doc(db, "invites", code), data);
      };
      Backend.listenInvites = function(cb, onError) {
        var q = query(collection(db, "invites"), orderBy("createdAt", "desc"), limit(200));
        return onSnapshot(q, function(snap) {
          var items = [];
          snap.forEach(function(d) { items.push(inviteData(d)); });
          cb(items);
        }, function(e) {
          console.error("listenInvites failed", e);
          if (onError) onError(e);
        });
      };
      // "Disable" = no seats left (maxUses := uses); the code stays listed for the record.
      Backend.disableInvite = function(code, uses) {
        return updateDoc(doc(db, "invites", code), { maxUses: uses });
      };
      Backend.deleteInvite = function(code) {
        return deleteDoc(doc(db, "invites", code));
      };
      Backend.updateInviteSeats = function(code, newMaxUses) {
        return updateDoc(doc(db, "invites", code), { maxUses: newMaxUses });
      };
      Backend.requestInvite = function(name, city, note) {
        if (!Backend.user) return Promise.reject(new Error("No user"));
        return setDoc(doc(db, "waitlist", Backend.user.uid), {
          name: String(name || "").slice(0, 50),
          city: String(city || "").slice(0, 50),
          note: String(note || "").slice(0, 100),
          createdAt: serverTimestamp()
        });
      };
      Backend.listenWaitlist = function(cb, onError) {
        var q = query(collection(db, "waitlist"), orderBy("createdAt", "asc"), limit(200));
        return onSnapshot(q, function(snap) {
          var items = [];
          snap.forEach(function(d) {
            var data = d.data({ serverTimestamps: "estimate" });
            data.uid = d.id;
            items.push(data);
          });
          cb(items);
        }, function(e) {
          if (onError) onError(e);
        });
      };
      Backend.deleteWaitlist = function(uid) {
        return deleteDoc(doc(db, "waitlist", uid));
      };
      Backend.listenMembers = function(cb, onError) {
        return onSnapshot(collection(db, "members"), function(snap) {
          var items = {};
          snap.forEach(function(d) { items[d.id] = d.data({ serverTimestamps: "estimate" }); });
          cb(items);
        }, function(e) { if (onError) onError(e); });
      };
      Backend.listenProfiles = function(cb, onError) {
        return onSnapshot(collection(db, "profiles"), function(snap) {
          var items = {};
          snap.forEach(function(d) { items[d.id] = d.data(); });
          cb(items);
        }, function(e) { if (onError) onError(e); });
      };

    }).catch(function(e) {
      console.error("Firebase load failed, demo mode fallback", e);
      Backend.isReal = false;
    });
  } else {
    Backend.ready = Promise.resolve();
  }
})();
