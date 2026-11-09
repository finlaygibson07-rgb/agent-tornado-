# V4 — the repair loop

A copy of `V3/agent-tornado`, plus the one thing V3 could not do: **a loop that
actually repairs a repository**, on your machine, with the local model in the
loop and a copy you can throw away. It also reads the web, and the reading is
done by **Scrapin** — the Scrapling fork in `finlaygibson07-rgb/Scrapin`.

V4 runs on **port 8800** so V3 (8799) can be open at the same time.

## What this folder is

This is the record of V4: what it does, how the web hand is held shut, and what
was verified by running it. The application code itself lives alongside it — see
`web-access.md` for where it sits and how to run it.

- **The loop.** Point it at a repo with a failing suite; it copies the repo into a
  scratch folder, edits **the copy**, reruns the tests after each change, and hands
  you a diff. Up to 12 turns, up to 6 files written. Your repo is never written.
- **The web hand.** `read-web` reads one http(s) page as text. It is the only hand
  whose target comes from the caller, so the bridge holds it to rules: http(s)
  only, no credentials in the url, nothing that points back at this machine or a
  private network, and every redirect followed by the bridge itself, one hop at a
  time.
- **The engine.** The manifest's `engine` field is `auto`: Scrapin when
  `scrapling` is installed, the standard library otherwise, and the result always
  names which one ran. Pin `"engine": "scrapin"` to refuse rather than fall back.

## Install Scrapin

```sh
pip install "scrapling[fetchers]"
# or, to read with this fork's own code:
pip install -e /path/to/Scrapin[fetchers]
```

Only the plain HTTP fetcher is used. The stealth browser, proxy rotation and
Cloudflare solving stay switched off: a browser in the bridge would be a second
program making requests nothing checks.

## Verified, by running it

- 244 tests pass — 110 JavaScript, 134 Python; 15 manifests valid.
- The loop took the deliberately broken fixture repo from red to green against the
  real bridge.
- `read-web` read `https://example.com/` through the bridge with
  `"engine": "scrapin"`, and followed a real `http://github.com/` →
  `https://github.com/` 301 one hop at a time.
- A 302 to `127.0.0.1:8800` is refused with one request made; a redirect to a
  `.local` name is refused; a six-hop chain stops at the limit.
