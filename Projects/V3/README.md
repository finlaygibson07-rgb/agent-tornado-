# V3

This folder contains a copy of agent tornado after the 2026-09-28 improvement pass.

- Snapshot: `agent-tornado/` (the whole app: `index.html`, the five scripts plus `model.js`, the `hands.py` bridge, tools, tests, launcher)
- Built on: the agent tornado sandbox (a standalone clone of `Projects/agent-vortex` from this repo, kept in the author's vault)
- Copied from the sandbox, excluding runtime state (`.run/`, `runs/`, `tools/.audit.jsonl`)
- What changed: see [`improvements.md`](improvements.md) (15 of 24 items done, every P1)
- Tests: 209/209 pass inside this folder (98 JS, 111 Python)

What V3 adds over the first sandbox version:

- **Hands security:** `path` arguments held to `roots`, no argument can become an option, `confirm` sent only after a real yes, model-proposed values ask before running, the origin is pinned to the bridge's port, the `Host` header is checked, and `http` hands are loopback-only unless `allowRemote`.
- **Model path:** one Ollama client (`model.js`) with schema-constrained replies. The brief is parsed first and the model may only add sub-steps under its leaves, so a typed outline is never flattened.
- **Simulation:** executed hands report their outcome (`run.report`), so a failing step grows `verify` helpers. `measure.js` output is unchanged.
- **Runs:** a *Saved runs* list in the Task pane, open-by-id, and typed arguments saved as you type.
- **Grammar:** `note: like this`, URLs and times no longer nest.
- **Bug fixes:** the page follows the port of the bridge that served it, and per-request dry runs are audited as dry runs.

It runs on its own: double-click `agent tornado.app` in `agent-tornado/`, or `python3 hands.py --start`. Only one bridge can hold port 8799; to run a second copy use `TORNADO_PORT=8800 ./launch.command`.

The canonical visualiser in `Projects/agent-vortex/` is untouched.
