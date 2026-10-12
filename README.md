# MomSakhi — clickable prototype

> **A sakhi for every stage of motherhood.** *Sakhi* (सखी) means a close friend.
> No judgement, just moms: a moderated, judgement-free community app for moms
> anywhere in the world — in India and abroad (USA, UK, Canada, UAE, Singapore, Australia…).

Personal project prototype (not UCP work). Pure static HTML/CSS/JS with mock data: no backend,
no build step, no API keys. Every person, post and event is fictional; avatars are initials only.

## Run it

```bash
cd ~/aangan && python3 -m http.server 8765
```

Open **http://localhost:8765/** — on a laptop it shows in a phone frame with quick links to every
screen; on a phone it fills the screen. Opening `index.html` directly also works.

**Rename the app:** change `brand.name` in [`data.js`](data.js) — that's the only place.

## Screens

| # | Screen | Route | What to try |
|---|--------|-------|-------------|
| 1 | Welcome | `#welcome` | Brand, promise, "Continue with Google" / "Continue with phone" |
| 2 | City (optional) | `#onboard/city` | Type any city worldwide or pick a suggestion (Pune, San Jose, London, Dubai…); "Skip for now" — only Meetups & Nearby need it |
| 3 | About you | `#onboard/about` | Nickname, anonymous-by-default toggle, kids' stages, 10 languages |
| 4 | Verification (mock) | `#onboard/verify` | Phone code or Google account check → "Enter MomSakhi" |
| 5 | Home feed | `#home` | 9 circles, posts (anonymous or nickname), Hug / Been there / Helpful reactions — no downvotes |
| 6 | Circle | `#circle/<id>` | Join, filtered posts, "Ask in this circle" |
| 7 | Ask | `#ask` | Pick circle, anonymous toggle, **"See the kindness check in action"** |
| 8 | Question detail | `#q/p1` | Verified-expert (IBCLC) reply, ⋯ report/block/hide, reply box with kindness check |
| 9 | Nearby | `#nearby` | Opt-in first (off by default) → stylised neighbourhood map + mom cards → "Say hi" → mock accept unlocks chat |
| 10 | Meetups | `#meetups` | Stroller walk at Shoreline, Las Palmas playdate, Diwali potluck… RSVP + "Going" tab |
| 11 | Chat | `#chat/m1`, `#chats` | 1:1 chat with mock replies, ⋯ block/report |
| 12 | Me | `#me` | Anonymous default, nearby visibility, who can message me, blocked list, guidelines, reset demo |

Screenshots of every screen (390×844 @2x) are in [`screenshots/`](screenshots/).

## What's mocked vs real
 
| Real (works in the browser) | Mocked |
|---|---|
| Navigation, all screens, deep links | Phone OTP / Google account verification (simulated delay & demo accounts; both sign-in methods are simulated in this front-end demo with no backend) |
| Posting questions & replies, reactions, RSVPs, privacy settings, block/hide — saved in `localStorage` | Other moms accepting your "hi" (auto-accepts after ~2.5s) and chat replies (canned) |
| Kindness check (client-side phrase list + curated rewrite) | Moderation / reports (toast only), expert verification |
| Neighbourhood-only map (inline SVG, no map API) | All people, posts, events and counts |

"Reset demo" on the Me tab clears local state.

## Tests & screenshots

```bash
# structural tests (stdlib only)
python3 -m unittest tests/test_aangan_web.py
# re-shoot all screens + smoke-test the JS (needs Playwright; fails on any page error)
python3 scripts/screenshots.py
```

## Next steps

1. **Share a public link** (it's static, so any of these take minutes):
   - **Netlify Drop** — drag the repo folder onto app.netlify.com/drop → instant URL.
   - **GitHub Pages** — push the repo, enable Pages from the repo root (`main` / `/`).
   - **Firebase Hosting** — `firebase init hosting` (public dir `.`) → `firebase deploy`.
2. **Real backend** — Firebase Auth (Google sign-in + phone OTP) + Firestore for posts/circles/chats,
   server-side moderation for the kindness check, and coarse geohash-to-neighbourhood bucketing so
   exact location is never stored.
3. **Name & brand** — renamed to MomSakhi (2026-10). Before launch: attorney
   clearance in India (a "MySakhi" mark is registered in class 45), test the tagline with a few
   moms, and get a proper logo/illustration set. Internal ids (repo, `aangan-6a58c` Firebase
   project, `aangan.*` storage keys) keep the old name on purpose.
4. **Pilot** — 20–30 MV/Sunnyvale moms, measure weekly posts per member and hi→chat conversion.

## Installable app (Add to Home Screen)

`manifest.webmanifest`, `icons/` (regenerate with `python scripts/make_icons.py`)
and `sw.js` make MomSakhi installable. The service worker caches only the
same-origin app shell; it never intercepts Firebase, Google sign-in, gstatic
or any other cross-origin request, so the live feed stays live.

When you bump the `?v=` cache string in `index.html`, set the same value as
`VERSION` in `sw.js` (a unit test checks this) so installed apps update.
