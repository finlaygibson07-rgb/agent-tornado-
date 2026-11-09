# hands

Drop a `.json` file in here and the tornado gains a new hand. No restart, no
registry to edit — hit **Rescan** in the app's Hands panel (or `POST /api/reload`)
and it appears.

This folder is the whole interface. `hands.py` reads every `*.json` in it, and it
will only ever run what those files declare. There is no endpoint anywhere that
accepts a command from the app.

## The shape of a manifest

One tool per file, or several grouped under `"tools"`:

```json
{
  "id": "read-file",
  "name": "Read a file",
  "kind": "file-read",
  "description": "Shown in the Hands panel and used for matching.",
  "matches": ["read", "open", "verify"],
  "roots": ["$HOME/Documents"],
  "args": {
    "path": {
      "type": "string",
      "required": true,
      "description": "Absolute path to the file."
    }
  }
}
```

`id` is lowercase with dashes, 2–63 characters. `kind` is one of the five below.
`matches` is a list of words; the decomposer binds a tool to an agent when the
agent's clause mentions one of them, so pick words you would actually use in a
brief.

## The six kinds

| kind | what it does | must declare |
|---|---|---|
| `shell` | runs a fixed argv, no shell involved | `argv` |
| `file-read` | reads a UTF-8 file | `roots` |
| `file-write` | writes a UTF-8 file — **always destructive** | `roots` |
| `http` | one pinned request | `url` |
| `web-read` | one page from the internet, as text | a `url` argument, and `allowRemote` |
| `copy-tree` | copies a folder into an empty one, leaving out links that lead outside it | `path` arguments `src` and `dst` |

### `shell`

```json
{
  "id": "list-dir", "kind": "shell", "name": "List a directory",
  "argv": ["/bin/ls", "-la", "{path}"],
  "roots": ["$HOME"],
  "cwd": "$HOME",
  "timeout": 10,
  "args": { "path": { "type": "path", "required": true } }
}
```

`{name}` placeholders must match a declared argument — an undeclared placeholder
is refused at load time, not at call time. Values are substituted into single argv
elements and passed straight to `execvp`. There is no shell, so `; rm -rf /`,
backticks and `$()` are inert text. `timeout` defaults to 20s and is capped at 600.

Give any argument that names a file or folder `"type": "path"`: it is then resolved
and held to `roots` exactly as a file tool's path is, so `ls {path}` cannot list
outside them. A value may also never start with `-`, because the program would read
it as an option (`node --test --eval=…` runs code). Put a literal `"--"` in `argv`
before a placeholder that legitimately needs a leading dash, as `search-text` does
for its pattern.

A shell hand does **not** inherit the bridge's environment. It gets `PATH`, `HOME`,
`USER`, `LOGNAME`, `SHELL`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TMPDIR`, `TERM` and `TZ`,
and nothing else, so an API key in the shell you launched from is not handed to a
test suite. Name anything more it needs in `"passEnv": ["NODE_OPTIONS"]`. A command
runs in its own process group, and a timeout kills the whole group, so workers a
test runner started do not outlive the call.

### `copy-tree`

```json
{
  "id": "copy-repo", "kind": "copy-tree", "roots": ["$HOME"],
  "args": {
    "src": { "type": "path", "required": true },
    "dst": { "type": "path", "required": true, "roots": ["$HOME/Documents/agent-tornado/work"] }
  }
}
```

Copies `src` into `dst`, which must be empty or not exist yet, and which may not
sit inside `src` (or the other way round). A symlink is copied only when it is
relative and lands inside `src`. Any other link (to `~/.ssh`, to `/etc`, or an
absolute link back into the original) is left out and named in the result. A
diff between the original and the copy therefore shows a left-out link as deleted.
That is the copy being safe, not the loop deleting anything.

### `file-read` / `file-write`

```json
{
  "id": "write-note", "kind": "file-write", "name": "Write a note",
  "roots": ["$HOME/Documents/agent-tornado"],
  "args": {
    "path": { "type": "string", "required": true },
    "content": { "type": "string", "required": true }
  }
}
```

A path is resolved with symlinks followed, then checked against `roots`. Anything
outside is refused — including `..` and a symlink that points out. `file-write` is
forced destructive: even if you write `"confirm": false`, the bridge overrides it,
and the app will ask before every call.

### `http`

```json
{
  "id": "ollama-status", "kind": "http", "name": "Check the local model",
  "url": "http://127.0.0.1:11434/api/tags",
  "method": "GET",
  "args": {}
}
```

`url` is the manifest's, not the request's — a caller cannot point it somewhere
else. An `http` hand is **loopback-only** unless the manifest sets
`"allowRemote": true`, and the host part of the URL can never be a placeholder. An
argument may still fill the path (`"url": "https://api.example/{id}"` with
`allowRemote`), which is powerful and worth thinking about before you write it.

### `web-read`

```json
{
  "id": "read-web", "kind": "web-read", "name": "Read a web page",
  "allowRemote": true,
  "engine": "auto",
  "args": {
    "url": { "type": "string", "required": true },
    "max_chars": { "type": "int", "default": 12000 }
  }
}
```

`engine` picks who reads the page. `"auto"` (the default) uses **Scrapin** — the
Scrapling fork — when `scrapling` is installed, and the standard library when it is
not; `"scrapin"` refuses to fall back and tells you `pip install "scrapling[fetchers]"`;
`"stdlib"` never imports anything optional. The result always names the engine that
ran, so `"auto"` cannot pass one off as the other. Whichever engine reads it, the
bridge does the url checking and follows redirects itself, one hop at a time.

`"ego"` renders the page in **Ego Lite** (a Chromium for agents) with its scripts
run, so a page painted in after load can be read, and then Scrapin reads the
rendered HTML (`"engine": "ego+scrapin"` in the result; `"ego"` alone when Scrapin
is not installed). It needs `"egoProfile"`: the id of an **empty** Ego Lite profile,
signed in to nothing, because the model that asks for a page reads untrusted text
and must not browse as you. `"Default"` is refused outright. With a profile set,
`"auto"` prefers ego. Each read runs in a fresh task space that is closed after it.
The browser is told to refuse every request to this machine and to private ranges
(redirects and the page's own requests included), and the address it finally
lands on is checked again before any text comes back. Find your profile's id with:

```sh
ego-browser nodejs -e 'console.log(await profiles())'
```

This is the one kind whose target comes from the caller, so it is held by rules
rather than by the manifest: http(s) only, no credentials in the url, no path
back to this machine or a private network, every redirect re-checked, and the name
resolved and refused by address at call time. It returns the page's text (HTML
stripped, scripts and styles dropped), never a download, and never more than
`max_chars`. It must say `"allowRemote": true` even to load — a hand that can
reach the internet should never be a surprise in a folder you dropped something
into.

## Arguments

```json
"args": {
  "count":  { "type": "int",    "default": 3 },
  "loud":   { "type": "bool",   "default": false },
  "mode":   { "type": "string", "enum": ["fast", "careful"] },
  "path":   { "type": "path",   "required": true, "description": "..." }
}
```

Types: `string`, `int`, `number`, `bool`, `path` (held to `roots`; needs them). Unknown arguments in a call are refused
rather than ignored, and `enum` is enforced.

A `path` argument may declare its own `roots`, which replace the tool's for that
argument. That is how one hand reads from anywhere in `$HOME` but writes only
under `work/`, as `copy-repo`'s `dst` and the diffs' `b` do.

## Roots and `$VARS`

`$HOME`, `$TORNADO_VAULT` and any other environment variable expand, and `~`
works. **An unset variable fails loudly at load time** rather than silently
resolving against the working directory — `--check` will tell you. A root of `/`
is refused outright: it would make every path "inside".

The shipped roots are deliberately wide on read (`$HOME`) and narrow on write
(`$HOME/Documents/agent-tornado`). Narrow them to what you actually want this
thing touching. Being able to read your whole home directory is a real
capability; you should decide whether you meant to grant it.

## Safety rails you cannot turn off in a manifest

- Only manifests in this folder can run. No arbitrary commands, ever.
- Destructive tools always confirm.
- File access is confined to declared roots, after symlink resolution, and so is
  every `path` argument to a shell hand.
- No argument can become an option to the program it is passed to.
- `http` hands stay on this machine unless the manifest says `allowRemote`.
- 30 invocations per 10 seconds, so a runaway loop cannot hammer the machine.
- Every call, refusal and rate-limit is appended to `.audit.jsonl` in this folder.
- The server binds to loopback and rejects browser requests from any origin but
  its own, port included, and any request whose `Host` is not this bridge.
- Every `/api` call except `/api/health` needs the bridge's token, in an
  `X-Tornado-Token` header. The bridge makes a new one each time it starts, writes it
  only to its own `0600` record in `.run/`, and hands it to the app window in the
  url's `#fragment`, which a browser never sends to a server. A window opened some
  other way shows the hands as **locked**. Open the app with `./launch.command`.
  `fix.js` reads the token from `.run/` itself.
- Shell hands get a cut-down environment, and a timeout kills the whole process group.

## Checking your work

```sh
python3 hands.py --check     # validate every manifest and list what loaded
python3 hands.py --dry-run   # serve, but plan calls instead of executing them
```

`--dry-run` is the safe way to watch a plan come together before you let it touch
anything.
