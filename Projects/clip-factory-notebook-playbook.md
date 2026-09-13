---
title: "clip-factory — what to steal from the clipping notebook"
tags: [clip-factory, research, roadmap, clipping]
status: proposal
source: "[[clip-factory-research-notebook]]"
created: 2026-09-10
---

# clip-factory: what to take from the clipping notebook

> [!info] Built from [[clip-factory-research-notebook]] (Gemini Notebook, 44 sources) and checked
> against the repo as it stood on 2026-09-10. Project: [[clip-factory]] · state: [[clip-factory-handoff]].
> These are proposals. Nothing in the repo has been changed.

## The big one: licensed campaign footage fixes three problems

Campaign marketplaces (**Vyro** at $3 per 1k views, **Whop Content Rewards**, **Sx Bot Clipify**)
give clippers source footage they're licensed to use, and pay per verified view. That handles
three open items at once:

1. **Blocker §4b (no real talking video):** a campaign's source video becomes the first real
   Phase-2 run.
2. **Copyright / Content ID risk:** the footage is licensed. That's the notebook's own "legal
   shield" advice.
3. **A reason to exist:** monetisation, measured in the same unit the retention bar cares about.

**How it maps onto the repo:**
- Turn each campaign brief into a profile, e.g. `profiles/campaigns/<name>.yaml`, holding the
  logo overlay (goes in the existing `frame.overlay` slot), banned content, allowed platforms,
  and required tags/links.
- One dedicated account per creator or niche. The notebook says mixed pages get far less reach,
  which matches the roadmap's *variant render per destination account*.
- How to pick a campaign: **≥60% of budget left**, opinion or emotion-led source (mindset,
  self-development and AI/tech do best), 2–3 platforms allowed. Read the brief closely:
  logo-placement misses get clips rejected and unpaid.
- CPM by niche: crypto $4–9 · finance $4–6 · SaaS/B2B $3–6 · gaming $1–4. For clipples,
  **AI/tech or SaaS** fits the voice and pays well. Steer clear of crypto gambling (see the
  Forbes source).

## Feature ideas, mapped to the slices

| Idea (tool it comes from) | Slice | What it becomes here | Effort |
|---|---|---|---|
| **Custom natural-language criteria** (Choppity) | `clip-highlight` | `--criteria "only controversial opinions"` fed into the `--llm` rerank prompt; each campaign profile can carry its own | S, needs an LLM key in `.env` |
| **Virality score + why the hook works** (Opus Clip) | `clip-highlight` / `clip-review` | We already emit `score` and `reason`. Rescale to 1–99, sort the review page by it, post the strongest first. `learn.py` already tunes weights to *my* Keep/Kill calls, which Opus doesn't do | S |
| **Word-level trimming** (Descript) | `clip-render` | Already on Wave 2's list as dead-air removal. Extend `clip-review` trims to "delete these words" | M |
| **Covering stagnant stretches** (Runway B-roll) | `clip-render` | §D6 says the pipeline never draws, so the §D version cuts to **pre-drawn plates** from the asset kit plus punch-ins. This targets the failing retention bar directly (`max_static_s` 12–16 s against a 3.0 s bar) | M, needs the asset kit |
| **Kinetic word-by-word captions** (Submagic) | `clip-render` | Already built (gold active word). Wave 2's emphasis captions are the next step | done / Wave 2 |
| **Upload-triggered intake** (Bytecap) | new cron | `hermes cron` polls a source channel's uploads playlist through the YouTube Data API (1 unit per call) and runs `clip-pipeline` on anything new | S |
| **Outlier detection** (Virlo) | new `clip-scout` | Flag videos beating their channel's median views-per-hour (Data API stats) to choose sources; drop creators who've plateaued. This is Wave 2's R8 "channel freshness" | M |
| **Multi-signal peaks** (ViddyFlow chat replay) | `clip-highlight` | Use viewers' timestamp comments ("3:41 😂") from `commentThreads` (official API) as a second signal next to transcript and loudness | M |

## Safe zones: one concrete fix found

The notebook's rule is to keep art and text out of the **top 15%** and **bottom 25%**.

- **Captions pass.** `y_center 0.66` with 92 px type puts the caption band at about 60–72% of
  frame height, clear of the bottom 25%.
- **The thumbnail hook is too high.** `thumbnail.y_center 0.2` with 108 px type and a 3-line
  hook gives a block that starts around **y≈175 px (9%)**. The 4:5 re-crop line in
  `assets/guides/make_guides.py` is at **285 px**, so the top line of a 2–3 line hook gets cut
  off in feed previews.
  **Suggested fix:** `thumbnail.y_center: 0.27` in `profiles/render/default.yaml`, which starts
  3 lines at about 305 px. The measurements are approximate (they depend on font metrics), so
  confirm on a rendered thumbnail.
- The guide PNG marks top UI at 8% and bottom at 20%. Consider raising it to the notebook's
  15% / 25%.

## Not building these (they conflict with standing rules)

> [!warning] These parts of the notebook conflict with the project's refusals and with platform rules
> - **AI auto-replies and DMs "to trigger the algorithm"** (Viral Day). That's engagement
>   manipulation; the notebook's own VerityAI source says it can be illegal. It also breaks
>   *official APIs only, no browser puppeteering*.
> - **"AI swarms" / synthetic consensus / IO Factory patterns.** That's coordinated inauthentic
>   behaviour. Platforms ban whole networks for it, and the notebook's campaign answer explains
>   that API-linked tracking and public leaderboards catch it.
> - **Many accounts:** fine as long as each one is real, single-niche, and posts through official
>   APIs. Still no automated account creation.
> - **Finance section (bond ladders etc.):** outside this project's scope, and not something I'll
>   give advice on.

## The supercell / tornado visualizer

This is worth doing for a **dashboard**, not inside the clips. Inflow = intake queue,
mesocyclone = highlight scoring, tornado = published clips, debris width = verified views. To
stay inside §D, draw it in the woodcut register (hatched storm, eight-point star, cream on warm
black) rather than neon.

## Revised next actions

- [ ] **Me:** pick one campaign with ≥60% budget left, in AI/tech or SaaS if there is one. Its
      source video is the Phase-2 test run.
- [ ] **Me:** OAuth clicks (unchanged, [[clip-factory-handoff]] §4a).
- [ ] **Agent:** `thumbnail.y_center` 0.2 → 0.27, then regenerate the guide PNG.
- [ ] **Agent:** `--criteria` on `clip-highlight --llm`, plus an LLM key in `~/.hermes/.env`.
- [ ] **Agent:** `profiles/campaigns/` schema (logo overlay, banned content, platforms, criteria).
- [ ] **Agent:** resume Wave 2 (dead-air removal, punch-ins, plates). It's the fix for the
      failing retention bar.
- [ ] **Later:** `clip-scout` (outliers + freshness), upload-triggered cron, comment-timestamp
      signal.
