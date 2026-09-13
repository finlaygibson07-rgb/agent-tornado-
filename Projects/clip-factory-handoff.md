---
title: clip-factory handoff
tags: [project, ai-agents, hermes, clipping, handoff]
status: phase-2-waiting-on-finlay
created: 2026-09-10
updated: 2026-09-13
repo: ~/clip-factory
source: ~/clip-factory/HANDOFF.md
---

> [!info] Mirror of `~/clip-factory/HANDOFF.md`
> Kept in sync from the repo. Companion note: [[clip-factory]].

# HANDOFF — clip-factory, as of 2026-09-13

Written to carry full context into a fresh session. Read this first, then `BRIEF.md` and
`docs/architecture.md`. Supersedes the 2026-09-10 evening handoff.

**Since 2026-09-10 evening:** the session's uncommitted work (batch runs, daily-quota
scheduling, `--criteria` passthrough, multi-id approve) is committed, and both wave-2
worktrees (§2a below) are reviewed, tested, merged into `build/phase1-complete`, and removed.
Nothing new is blocked; the blockers are unchanged — see §4.

---

## 1. What this project is

A local-only, multi-agent "content operation" Finlay prompts and delegates through.
**Project #1 is a video clipping pipeline**: long-form video → several vertical 9:16 short
clips → published to YouTube.

The orchestrator **already exists** — Hermes Agent (Nous Research) v0.21.0 at `~/.hermes`,
`hermes` on PATH. Do not build a competing runtime. Capability rides at the edges as Hermes
skills under `~/clip-factory/skills/`.

**Working method** (Finlay's stated agreement): the bar is a real reference, never an
adjective; fan out to a handful of worker sub-agents each owning a real slice; a separate
checker agent that did *not* write the code grades it. Phase 1 = build normally, no checker.
Phase 2 = handover. Phase 3 = checker on. **Phase 1 is done; Phase 2 is waiting on Finlay**
(a real source video, the OAuth clicks, the §B1 reference clips).

---

## 2. Pipeline status — all five slices built

| # | Skill | What it does | Check |
|---|---|---|---|
| 1 | `clip-ingest` | path/URL → `master.mp4` (H.264, short edge ≤1080, ≤30 fps CFR, rotation baked in) + 16 kHz `audio.wav` + word-timed `transcript.json` (faster-whisper, VAD) + `meta.json` (incl. `source_info` title/url/channel) | `selfcheck.py` |
| 2 | `clip-highlight` | transcript → ranked, non-overlapping candidates snapped to whole words, each with hook, summary, keywords, reason. Offline heuristic (hook strength, clean boundaries, pace/density, loudness z-score, payoff / question→answer, sag penalty for dead stretches, length prior, fillers). `--llm` reranks via any OpenAI-compatible endpoint | `selfcheck.py` |
| 3 | `clip-render` | candidate → 1080×1920 MP4: YuNet face tracking (Haar fallback) with dead-zone hold / eased pan / hard cut, Caslon captions with gold active word, two-pass loudnorm to −14 LUFS, optional pre-drawn frame overlay. Sidecar `<id>.render.json` | `selfcheck.py` |
| 4 | `clip-package` | rendered clip → `<id>.package.json` (jsonschema-validated against the slice-5 contract) + 9:16 `<id>.thumb.jpg` (clean frame from master, largest early face, hook on a flat plate) | `selfcheck.py` |
| 5 | `clip-publish-youtube` | package → private upload + review queue. **Blocked on OAuth (§4)** | `selfcheck.py` |
| — | `clip-pipeline` | runs 1→5, publish as `--dry-run` (never uploads) | `tests/e2e.py` |

**Verified 2026-09-10:** all five `selfcheck.py` → `selfcheck OK`; A1 conformance (frontmatter,
≤60-char descriptions, section order, no machine paths) passes for all six SKILL.md files;
`tests/e2e.py` → `e2e OK` in ~52 s — real ASR on synthetic speech, a moving face, the
off-topic passage correctly skipped, both clips 100% face coverage with the expected hard
cuts, packages accepted by slice 5; a real `yt_publish.py --dry-run` on a fixture package
exits 0 with `privacy: private`.

**Not yet verified:** any run on real footage of a real person talking. There is no such video
on this Mac (`~/Downloads/IMG_4634.mov` has faces but no speech — whisper returns `"."`;
`mixdown-final-video.mov` is a 4 fps edit). That is the first thing Phase 2 needs.

```bash
export PATH="$HOME/.hermes/bin:$PATH"; cd ~/clip-factory
for s in clip-ingest clip-highlight clip-render clip-package clip-publish-youtube; do
  uv run --script skills/$s/scripts/selfcheck.py | tail -1; done
uv run --script tests/e2e.py | tail -1
```

---

## 2a. Added 2026-09-10 (autonomous run, sub-agents in git worktrees)

Finlay's direction for this stretch: *work alongside me* (three lanes — `BOARD.md`), then
*make the clips as addictive as possible — novelty is currency*.

| What | Where | State |
|---|---|---|
| Review page — Keep/Kill, timestamped notes, trims → `runs/<run>/reviews.json` | `skills/clip-review/` | merged, selfcheck OK, browser-tested |
| Active-speaker framing (mouth motion × speech-envelope change, hysteresis) + end-card slot | `skills/clip-render/` 0.2.0 | merged; 98.7% on the synthetic two-shot (`tests/twoshot_check.py`); **unproven on real footage** |
| Topic keywords, clause hooks from run-ons, `learn.py` (weights from reviews → `profiles/highlight/weights.yaml`) | `skills/clip-highlight/` 0.2.0 | merged, selfcheck OK |
| Retention bar + black-box grader | `docs/retention.md`, `tests/retention_report.py` | see §2b — mechanism built, real-footage verdict still open |
| Three-lane setup, checker prompts, asset-kit spec + 1080×1920 layout guide | `BOARD.md`, `docs/checker.md`, `docs/asset-kit.md`, `assets/guides/` | done |

## 2b. Wave 2 — retention, reviewed and merged 2026-09-13

The two wave-2 worktrees (stopped mid-run by Finlay on 2026-09-10 evening) were reviewed,
tested, and merged into `build/phase1-complete`:

- **render side** (`clip-render` 0.3.0) — `retention.py`: pattern-interrupt punches gated off
  cuts, emphasis-word timing, per-clip variant seeding (caption offset/colour), dead-air
  tightening capped at 1.08×, a teaser segment ahead of the body, `--no-retention` escape
  hatch. Was uncommitted mid-edit on 2026-09-10; its own selfcheck now runs clean and was the
  review gate for merging — clear (previously untested).
- **highlight side** (`clip-highlight` 0.3.0) — went further than the 2026-09-10 note
  expected: R8 (channel freshness) was in fact finished (commit `3162186`, after the
  checkpoint `94ab93c` this file previously cited), plus `--criteria` natural-language
  filtering and per-candidate LLM diagnostics. selfcheck OK.

Both worktrees are merged and removed (`.claude/worktrees/agent-*`, branches
`worktree-agent-*` — gone). Interface: candidate `teaser: {start_s, end_s, text} | null`.

**`docs/retention.md`'s R3 bar (`max_static_s ≤ 3.0`) is not fully settled:**
`tests/retention_report.py` on the crafted selfcheck fixture clears it (2.48s). On
`tests/e2e.py`'s real-synthetic-speech fixture it's close but still over (3.3–3.6s vs 3.0s;
previous baseline there was 12–16s — real progress, not a full pass). Real speech has
different pause shapes than the crafted fixture. This won't be truly known either way until
run on real footage (§4b) — treat it as open, not solved.

All on branch `build/phase1-complete`; `main` untouched, not pushed. Full suite as of
2026-09-13: five selfchecks OK, `twoshot OK`, `e2e OK`. Also committed: `batch.py` (resumable
multi-source runs), `schedule.py` (daily-quota-capped uploads scanning `reviews.json` for
`keep` verdicts), `--criteria` threaded through `clip-pipeline`, `review_queue.py approve`
now takes multiple ids — this was the session's uncommitted work as of the 2026-09-10 evening
handoff, verified (all selfchecks + e2e) and committed 2026-09-13.

---

## 3. Where everything lives

| What | Path |
|---|---|
| Repo | `~/clip-factory` — work is on branch **`build/phase1-complete`** (committed, not merged to `main`, not pushed). Merge when happy. |
| Hermes | `~/.hermes` · config `~/.hermes/config.yaml` · secrets `~/.hermes/.env` |
| `uv` (Python 3.11) | `~/.hermes/bin/uv` — **not on the default PATH**, export it first |
| ffmpeg | **none installed, none needed** — scripts use `$CLIP_FACTORY_FFMPEG` → PATH → the static ffmpeg 7.1 inside the `imageio-ffmpeg` wheel (libx264, libass, videotoolbox). No ffprobe needed. |
| Render style | `profiles/render/default.yaml` (captions, reframe tuning, frame overlay, thumbnail) |
| Face model cache | `~/.cache/clip-factory/models/face_detection_yunet_2023mar.onnx` (230 KB, OpenCV zoo) |
| Whisper weights | Hermes' HF cache already has `Systran/faster-whisper-base` |
| OAuth client secret | `~/.config/clip-factory/youtube_client_secret.json` (chmod 600, outside repo) |
| OAuth token | `~/.config/clip-factory/youtube_token.json` — **does not exist yet** |
| Env vars | `~/.hermes/.env` → `CLIP_FACTORY_YT_CLIENT_SECRET`, `CLIP_FACTORY_YT_TOKEN`; optional `CLIP_FACTORY_LLM_API_KEY` / `NVIDIA_API_KEY` for `--llm` (not set) |
| Review queue | `~/clip-factory/runs/_review_queue/` (gitignored) |
| Test runs | `runs/_e2e` (rebuilt by `tests/e2e.py`), `runs/_fixture`, `runs/fixture-face` — synthetic, gitignored, safe to delete. The review queue is empty. |
| Obsidian mirror | `~/Library/Mobile Documents/com~apple~CloudDocs/VALT/asher star/clip-factory.md` |

**Run scripts as:** `uv run --script <path>` — **not** `uv run python <path>`, which silently
ignores the inline PEP-723 dependencies.

### Google / YouTube

| Thing | Value |
|---|---|
| Google account | `finlaygibson07@gmail.com` |
| Target channel | **clipples** — a Brand Account created 2026-09-07, managed by that gmail |
| Other channel | "Finlay R. Gibson" — the personal channel, shows his real name publicly, **not** the target |
| GCP project (primary) | `clip-factory-508002` — API enabled, scopes registered, OAuth Desktop client created |
| GCP project (fallback) | `clipfactory-yt-508204` — half-built, no scopes, no client. Delete unless needed. |

---

## 4. Blockers — both need Finlay's hands

### 4a. OAuth (unchanged) — read before touching Google Cloud

**Symptom:** authorizing throws `Error 403: access_denied — clip-factory has not completed the
Google verification process ... can only be accessed by developer-approved testers.`

**Cause:** the OAuth app is in **Testing**; a Brand Account (clipples) has no email and can
never be a test user. The fix is **Publish app** → Production, gated behind the Branding page
Save — and **Auth Platform config Saves fire zero network requests under browser automation**
(verified exhaustively across 2 contexts / 2 projects; suspected Grammarly extension). **Do not
spend another session automating it.**

**The manual steps (~2 minutes, `clip-factory-508002`):**

1. `https://console.cloud.google.com/auth/branding?project=clip-factory-508002` — click **Save**
   (nudge a field first if it looks inert).
2. `https://console.cloud.google.com/auth/audience?project=clip-factory-508002` — **Publish app**
   → confirm. Status must read **In production**.
3. ```bash
   cd ~/clip-factory && export PATH="$HOME/.hermes/bin:$PATH"
   uv run --script skills/clip-publish-youtube/scripts/yt_auth.py
   ```
   Pick `finlaygibson07@gmail.com` → *Advanced → Go to clip-factory (unsafe)* → **choose the
   `clipples` channel, not "Finlay R. Gibson"** → Allow.
4. `uv run --script skills/clip-publish-youtube/scripts/yt_auth.py --check` → must print
   `authorized OK` and `channel : clipples`.

The OAuth grant (step 3) is an authentication flow — Finlay does it, not an agent.

### 4b. A real source video

The pipeline has only ever run on synthetic fixtures. Needed: one real talking video
(podcast, talk, interview — speech-led) as a path or URL, plus its public URL if local.

### ~~4c. ffmpeg~~ — resolved 2026-09-10

No Homebrew needed; see §3.

---

## 5. How to run it

```bash
export PATH="$HOME/.hermes/bin:$PATH"; cd ~/clip-factory

# one source -> ranked, rendered, packaged clips + dry-run queue entries. Never uploads.
uv run --script skills/clip-pipeline/scripts/pipeline.py "https://youtu.be/ID" --out runs/ep12 \
    --top 3 --content-type podcast --speakers "Name"
uv run --script skills/clip-pipeline/scripts/pipeline.py ~/talk.mp4 --out runs/talk --url https://youtu.be/ORIG
uv run --script skills/clip-pipeline/scripts/pipeline.py URL --out runs/x --llm --criteria "strong opinions only"

# many sources (resumable; one line per source, optional "| key=value" fields — see batch.py)
uv run --script skills/clip-pipeline/scripts/batch.py sources.txt --batch runs/b01 --top 4
# after Keep/Kill in clip-review: upload kept clips within today's quota (PRIVATE), daily
uv run --script skills/clip-publish-youtube/scripts/schedule.py runs/b01 --plan
uv run --script skills/clip-publish-youtube/scripts/schedule.py runs/b01

# real upload — lands PRIVATE, writes a review-queue entry
uv run --script skills/clip-publish-youtube/scripts/yt_publish.py --packaged runs/ep12/clips/c01.package.json
uv run --script skills/clip-publish-youtube/scripts/review_queue.py list
uv run --script skills/clip-publish-youtube/scripts/review_queue.py approve <id>   # -> unlisted
uv run --script skills/clip-publish-youtube/scripts/review_queue.py approve ID1 ID2 ... --privacy public
```

Individual slices: each `skills/<slice>/SKILL.md` has How to Run / Quick Reference.

**Safety design, deliberately:** `profiles/youtube.yaml` sets `default_privacy: private` and
`require_manual_approve: true`; anything more public is clamped back. `review_queue.py approve`
is the only route to public; `clip-pipeline` only ever dry-runs. Do not weaken this without
Finlay explicitly asking.

**Refusals that stand regardless of scale:** no automated social-account creation, no browser
puppeteering of platforms, official APIs only.

---

## 6. Design direction — `REFERENCE.md` §D is authoritative

Early-modern woodcut / almanac + tattoo flash; signature motif the eight-point star; tone from
hatching density never fill; colour secondary to line work; **the pipeline composes pre-drawn
assets, it never draws** (§D6). Two separable layers: black-ink-on-cream drawing language
(Desgin pins 1–3) vs. Finlay's dark-ground gold-star collage treatment (pin 4).

How the build honours it: captions and thumbnails use the §D4 palette (cream `#FEFEFC`, warm
black `#151110`, gold `#B8913F` as the single accent), a keyline not a shadow, one flat plate
not a gradient. `frame.overlay` in the style composes a hand-made 1080×1920 PNG over every
frame — the slot for the §D6 asset kit, empty until the kit exists.

**Caption typography is provisional** (§D7): Big Caslon uppercase, chosen for the broadsheet
register, **not confirmed by Finlay**.

---

## 7. What to do next

**Needs Finlay (nothing public happens without these):**
- [ ] §4a OAuth clicks → `yt_auth.py --check` prints `channel : clipples`
- [ ] Supply one real talking video (+ its URL) → `clip-pipeline` → watch the clips — also the
      only way to settle whether retention (§2b) actually clears the bar
- [ ] Upload the best one privately with `yt_publish.py`, watch it on YouTube, `approve` it
- [ ] Fill `REFERENCE.md` §B1 with 3–5 reference clip URLs — **gates the Phase-3 checker**
- [ ] Confirm or replace the caption face (§D7); optionally drop an OFL `.ttf` into `assets/fonts/`
- [ ] `hermes skills install` the six skills (README "Wire it into Hermes")

**Agent work, once a real video exists:**
- [ ] Tune the highlight weights against real picks vs. Finlay's taste; add an LLM key and try `--llm`
- [ ] Active-speaker detection (currently: largest steady face wins — wrong for two-shots)
- [ ] Watch a real render for anything mechanical (punch-ins on every word, zoom on a cut) —
      the numbers can pass while it still looks robotic (`docs/retention.md` §"What the
      checker grades")
- [ ] Assemble the §D6 asset kit (frame overlay, end card, avatar/banner) from PD plates
- [ ] Review the "Draw inspo" board (79 pins) to deepen §D2/D3
- [ ] Variant-render per destination account (`docs/publishing.md` "machine" item 4)

---

## 8. Hard-won gotchas

1. **Brand Accounts cannot authorize while the app is in Testing.** Production is mandatory.
2. **The developer-contact email must commit as a chip** (press Enter) in the consent-screen
   wizard, or the app becomes unpublishable with no field marked invalid.
3. **Auth Platform config Saves cannot be automated** in this environment (§4a).
4. **`uv run python <script>` silently ignores inline dependencies** — always `uv run --script`.
5. YouTube quota: `videos.insert` = 1600 of 10,000 units/day ≈ **6 uploads/day**.
6. Custom thumbnails need a phone-verified channel; `yt_publish` downgrades that 403 to a warning.
7. **OpenCV 5.x dropped `cv2.data` (Haar cascades)** — skills pin `opencv-python-headless<5`.
8. **The Hermes default LLM (opencode free tier) refuses non-OpenCode clients** — `--llm` needs
   its own key (`CLIP_FACTORY_LLM_API_KEY` or `NVIDIA_API_KEY`).
9. **iPhone clips carry a −90° rotation flag**; ingest reports displayed dims and bakes rotation in.
10. **Whisper run-on punctuation** merges sentences ("…asked for, so what changed?"); the
    highlighter falls back to 0.7 s pauses, so some hooks start mid-thought.
11. **Dry runs write review-queue entries** (`state=dry_run`); use `--publish-mode preview` in
    `clip-pipeline` when experimenting.
12. `skill-seekers` returns empty content on `ffmpeg.org` (Texinfo HTML) — curl first, then
    `--html-path`; its generated SKILL.md always needs a hand rewrite for §A1.
