---
title: ink-sky — calibration log
tags: [project, agents, ink-sky, calibration]
status: three runs read by hand
source: ~/ink-sky/CALIBRATION.md
---

> [!info] Mirror
> This note mirrors `~/ink-sky/CALIBRATION.md`. See [[ink-sky]].


Stage 4 says the bar is calibrated by running the Scout by hand and reading every candidate,
and that there is no other way. This is that reading. The rubric was **not** changed — clause
VI and the Scout's own orders say a disagreement with the rubric is written down as a finding,
not smoothed into the scores. Every change proposed here is Finlay's call, not the Scout's.

## The runs

| # | query | swept | surfaced | outcome |
|---|---|---|---|---|
| 1 | `topic:cli language:rust stars:>800 pushed:>2026-03-01` | 10 | 0 | NOTHING |
| 2 | `topic:developer-tools language:typescript stars:>1000 pushed:>2026-06-01` | 10 | 0 | NOTHING |
| 3 | `topic:llm topic:agent stars:>2000 pushed:>2026-07-01` | 10 | 0 | NOTHING |

`signal_ratio` 0.000 over 30 swept, against a ceiling of 0.05. Run 3 skipped `OpenHands` at the
rejection gate, before any signal fetch — the archive worked on its second encounter.

Store: `calibration.db` (kept separate from the seeded `ink-sky.db`).

## Hand-picked check — stage 3's gate

| pick | structure | verdict |
|---|---|---|
| ripgrep | 97 | clears |
| zod | 99 | clears |
| request (archived, 2405 days) | 33 | held back: unmaintained |
| moment (maintenance mode, deprecated by its own authors) | **99** | **clears** |

The good ones clear and the dead one does not, so the gate passes. Moment is the finding.

## What the reading actually showed

**1. A three-week-old repo is indistinguishable from a proven one.** Eleven of thirty
candidates scored exactly 100. `days_since_commit: 0` plus a fast reply plus three contributors
saturates the Seal of Structure. `gitoxide` and a two-week-old agent wrapper tie. The seal as
written measures *recent motion*, not maturity — and the whole charter is an argument against
mistaking motion for worth. **Proposal (Finlay's call): a signal for age at first commit, or a
ceiling on what a repo under ~6 months old can score.** Either is a rubric change and per
`spec/CONTRACTS.md` §2 it means editing `scoring.ts` and its test in the same commit.

**2. Response latency flatters the small.** `median_issue_response_days` is taken over the last
30 *closed* issues. A maintainer answering their own three issues within the hour earns the
same +12 as a project with real triage. The signal is honest; the weight is not.

**3. `not_understood` is the commonest fate of a good repo, and that is the charter working.**
Every candidate scoring 100 was barred, because the mechanical note-writer could name no
improvement — it derives notes from measured absences (no tests, no changelog, slow replies),
so the better the signals, the less it can say. Clause V bars exactly that. The consequence is
worth stating plainly: **the deterministic Scout can only fault mediocre tools.** Naming what
would make a good tool better needs a reader. `Repo.revive()` is the door back in — a human
names the improvement and the thing returns to the queue.

**4. Nothing can clear the bar on GitHub alone, by construction.** `clearsBar()` wants three
voices and a Seal of Working; GitHub carries no voices (a star is not a voice — clause III).
So `signal_ratio` is 0 until Reddit lands in stage 5, and stage 4's ratio gate passes without
proving anything. **Do not read three NOTHING runs as evidence the bar is right.** It is
evidence the Scout is honest about having no outcome data yet.

**5. The rubric reads the commit graph, not the authors' own verdict.** Moment scores 99 while
its maintainers tell people to stop using it. A repo can be well-built, well-staffed, actively
committed, and still the wrong thing to adopt. GitHub's `archived` flag catches the dead ones;
it does not catch the ones in maintenance mode saying so in their README. This is the rubric's
real blind spot and no weighting change fixes it.

## What was not covered

- Reddit: not built. Stage 5.
- `stars_velocity_30d` currently records the star *count*, not a 30-day delta — recorded for
  the archive, never scored, so it changes nothing, but it is not yet what CONTRACTS names.
- Three runs is three. The gate asks for three consecutive runs read by hand; it does not make
  thirty candidates a representative sample of anything.
