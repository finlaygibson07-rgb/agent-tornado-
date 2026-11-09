---
title: V4 — the repair loop, and reading the web through Scrapin
date: 2026-11-09
tags:
  - agent-tornado
  - v4
  - scrapin
  - scraping
  - local-first
status: done
port: 8800
related:
  - "[[agent-tornado]]"
  - "[[agent-vortex]]"
  - "[[agent-tornado-improvements]]"
---

# V4 — the repair loop, and reading the web through Scrapin

V4 is V3 plus the one thing V3 could not do: a loop that **repairs a repository**
on this machine, with the local model in the loop and a copy you can throw away.
On top of that, it can now **read a web page** — and the reading is done by
**Scrapin**, the Scrapling fork in `finlaygibson07-rgb/Scrapin`.

V3 is untouched. V4 runs on **port 8800** so both can be open at once.

## What it does

- Point it at a repo with a failing suite. It copies the repo into a scratch
  folder, reads and edits **the copy**, reruns the tests after each change, and
  hands you a diff. Up to 12 turns, up to 6 files written.
- **Your repo is never written.** `copy-repo` only reads it.
- The loop names capabilities, never hand ids: `list_files`, `read_file`,
  `search_text`, `run_tests`, `write_file`, `read_url`, `finish`.
- `read_url` is the new one: mid-repair the model can look up a deprecation
  notice or an error message instead of guessing at it.

## The web hand

`read-web` in `V4/agent-tornado/tools/web.json`, kind `web-read`. It takes a url
from the caller, which is why it is held by rules rather than by its manifest.

- http(s) only — no `file:`, `data:`, `javascript:`
- no username or password in the url
- nothing that points back at this machine: `localhost`, `*.local`, and any
  literal address that is not public
- the hostname is resolved at call time and refused by address, so a name that
  lands on a router or a cloud metadata endpoint never gets a request
- **every redirect re-checked**, and with Scrapin as the engine the redirects are
  not merely re-checked afterwards: it is told `follow_redirects=False` and the
  bridge makes each hop itself, one at a time, capped at five
- at most 2 MB read, text rather than a download, no cookies, no credentials

The engine is chosen by the manifest's `"engine"` field:

| value | meaning |
|---|---|
| `auto` (default) | Scrapin when `scrapling` is installed, standard library otherwise |
| `scrapin` | refuse rather than fall back, and say how to install it |
| `stdlib` | never import anything optional |

The result always names the engine that ran (`"engine": "scrapin"` or
`"stdlib"`), and the dry run's plan names it before anything is fetched — so the
two can never be mistaken for one another.

## Install Scrapin

```sh
pip install "scrapling[fetchers]"                # published 0.5.1, the version the fork declares
pip install -e /path/to/your/Scrapin[fetchers]   # or this fork's own code
```

Only the plain HTTP fetcher is wired up. Scrapin's stealth browser, proxy
rotation and Cloudflare solving are **not** used: a browser in the bridge would
be a second program making requests nothing here checks.

## Run it

```sh
cd V4/agent-tornado
./launch.command        # bridge on 8800, and the app
```

Then the **fix** tab: repo, goal, suite hand, run. Or `node fix.js` for the same
loop from a terminal.

## Verified, by running it

- 244 tests pass — 110 JavaScript, 134 Python; 15 manifests valid.
- The loop took `V4/fixtures/broken` from red to green against the real bridge.
- `read-web` read `https://example.com/` through the bridge, with
  `"engine": "scrapin"`, and followed a real `http://github.com/` →
  `https://github.com/` 301 one hop at a time.
- A 302 to `127.0.0.1:8800` is refused **with one request made**; a redirect to
  `localhost` is refused; a six-hop chain stops at the limit.

## What it will not do

- **No search.** It reads a url that is already known. No provider, no key.
- **No JavaScript rendering** with the plain fetcher, so anything painted in
  after load is invisible. Docs and changelogs yes; an app screen no.
- **No live-model run has been watched here** — this machine has no Ollama. The
  model-facing side is tested against a scripted stand-in.
- The address is checked by name and then connected by name, so a hostile DNS
  server could answer differently the second time. Written down rather than
  papered over.

## Where it lives

`V4/` in the project — `agent-tornado/` is the app, `fixtures/broken/` proves the
loop. Both READMEs (`V4/README.md`, `V4/agent-tornado/README.md`) carry the full
argument; `tools/README.md` documents the manifest fields including `engine`.
