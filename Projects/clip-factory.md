---
title: clip-factory
tags: [project, ai-agents, hermes, clipping]
status: phase-2-handover
created: 2026-09-03
updated: 2026-09-10
repo: ~/clip-factory
---

# clip-factory

> [!tip] Current state lives in [[clip-factory-handoff]] (mirror of `~/clip-factory/HANDOFF.md`)
> Full handoff — paths, blockers, next actions. Read that first on resume.

> [!info] Research: [[clip-factory-research-notebook]] (Gemini Notebook mirror, 44 sources) →
> what to steal from it, mapped onto the slices: [[clip-factory-notebook-playbook]]

A multi-agent "content operation" I prompt and delegate through, running **local-only** on my
Mac. Project #1 is a video **clipping pipeline**. Do one app at a time, then the next.

Repo: `~/clip-factory/` (git; 2 commits, the 2026-09-10 build is uncommitted). This note is
the human-readable mirror; the repo holds the working files.

## Status — 2026-09-10: all five slices built, Phase 1 done

| # | Slice | Skill | Status |
|---|-------|-------|--------|
| 1 | Ingest | `clip-ingest` | **built** — path/URL → `master.mp4` + 16 kHz `audio.wav` + word-timed `transcript.json` + `meta.json`. No ffmpeg install needed |
| 2 | Highlight | `clip-highlight` | **built** — ranked, non-overlapping candidates with hook, summary, keywords and a reason each. Offline scorer; optional LLM rerank |
| 3 | Cut & frame | `clip-render` | **built** — 1080×1920, face-tracked reframe (hold / ease-pan / hard-cut), Caslon captions with gold active word, −14 LUFS |
| 4 | Package | `clip-package` | **built** — schema-validated hand-off JSON + 9:16 thumbnail (clean face frame, hook on a flat plate) |
| 5 | Publish | `clip-publish-youtube` | **built** — uploads `private` into a review queue; `review_queue.py approve` is the only way public. Blocked on OAuth |
| — | All | `clip-pipeline` | runs 1→5, publish as a dry run — **never uploads** |

Verified: every slice's `selfcheck.py` passes; `tests/e2e.py` runs all five on a synthetic
fixture (real speech from `say`, a moving public-domain face) in under a minute — skips the
off-topic passage, 100% face coverage, correct hard cuts, packages accepted by slice 5.
**Not yet run on real footage** — no speech-led video exists on the Mac.

```bash
export PATH="$HOME/.hermes/bin:$PATH"; cd ~/clip-factory
uv run --script skills/clip-pipeline/scripts/pipeline.py "https://youtu.be/ID" --out runs/ep12 --content-type podcast
uv run --script skills/clip-publish-youtube/scripts/yt_publish.py --packaged runs/ep12/clips/c01.package.json   # lands PRIVATE
```

## What only I can do next

- [ ] **OAuth clicks** (~2 min): Branding → Save, Audience → Publish app, then `yt_auth.py`,
      pick **clipples** not "Finlay R. Gibson". Exact steps: `HANDOFF.md` §4a. Can't be automated.
- [ ] **Give it one real talking video** (+ its URL) → run `clip-pipeline` → watch the clips
- [ ] Upload the best one privately, watch it on YouTube, `approve`
- [ ] 3–5 reference clip URLs → `REFERENCE.md` §B1 (gates the Phase-3 checker)
- [ ] Confirm or replace the caption face — **Big Caslon is a provisional pick**
- [ ] Commit the build; `hermes skills install` the six skills (README "Wire it into Hermes")

## The orchestrator already exists — Hermes

**Hermes Agent** (Nous Research) v0.21.0 at `~/.hermes`, `hermes` on PATH. "Delegate by
Hermes" = this, not something to build: `delegate_task`, skills (`~/.hermes/skills/`),
`hermes cron`, `hermes kanban`, `hermes project`, `hermes moa`, memory + learning loop, a
`claude-code` skill that drives `claude -p` as a worker.

- Config: `~/.hermes/config.yaml` · secrets: `~/.hermes/.env` / `hermes secrets`
- Capability rides at the **edges** (skills), never the Hermes core — "Footprint Ladder" in
  `~/.hermes/hermes-agent/AGENTS.md`

## The method (the bar, not adjectives)

1. **The bar is a real reference** — a file, URL, or named product. Lives in `REFERENCE.md`.
2. **Fan out** to a handful of worker sub-agents, each owning one real slice.
3. **Maker/checker** — a separate agent that did *not* write the code grades it against the
   bar and returns specifics (file:line, timestamps).

- **Phase 1:** build normally, no checker loop — *done 2026-09-10*
- **Phase 2 (now):** one real clip end to end; I supply reference clips
- **Phase 3:** checker loop on, graded against the now-specific bar

## Profiles / the "account"

`profiles/youtube.yaml` — **active**, default `private`, `require_manual_approve: true`.
`tiktok.yaml` / `instagram.yaml` — `draft_only` until their official APIs are wired.
Per-content-type templates (`podcast`, `educational`, `gaming`, `own-longform`, `general`).
`profiles/render/default.yaml` — the §D look for captions, reframe tuning, frame overlay,
thumbnail.

## Design bar — REFERENCE.md §D

- Register: early-modern woodcut / broadsheet / almanac + tattoo flash. Signature motif: the
  **eight-point star**. Drawn quality first, colour second.
- Line work: tone from **hatching density, never fill**; line weight swells and tapers;
  imperfection is load-bearing. Fails: vector outlines, gradients, shadows, flat-fill shading.
- Palette (treatment layer): ground `#151110`, line `#FEFEFC`, gold `~#B8913F`. Warm black only.
- **The pipeline composes pre-drawn assets, it never draws.** `frame.overlay` in the render
  style is the slot for the hand-made asset kit (not assembled yet).
- Captions/thumbnails follow the palette: cream type, warm-black keyline (no shadow), gold only
  on the spoken word, one flat plate (no gradient).
- Open: caption face (Caslon provisional), "Draw inspo" board (79 pins) unreviewed.

## Constraints & refusals

- Local-only. Keys in `~/.hermes/.env`, never in repo or skill code.
- Publishing = **official platform APIs only**. **No** automated account creation, **no**
  browser-puppeteering of platforms.

## Environment notes

- **No ffmpeg / Homebrew needed** — scripts use the static ffmpeg inside the `imageio-ffmpeg`
  wheel. Always `uv run --script` (Hermes' `uv` at `~/.hermes/bin`), never `uv run python`.
- LLM rerank (`clip-highlight --llm`) needs `CLIP_FACTORY_LLM_API_KEY` or `NVIDIA_API_KEY` in
  `~/.hermes/.env` — the Hermes default (opencode free tier) refuses outside clients.
- `ffmpeg-video` reference skill staged at `~/skills-build/ffmpeg-video/` (not installed).
  `~/.hermes/skills/clipping-automation` covers the business side — no overlap.

## Roadmap beyond clipping

- Variant render per destination account; per-account `hermes cron` scheduling.
- TikTok / Instagram publish skills once their APIs are approved.
- **Connector portal** skill: paste a URL → auto-wire MCP / OpenAPI, draft-for-review the rest.
