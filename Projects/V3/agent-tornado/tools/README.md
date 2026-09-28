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

`id` is lowercase with dashes, 2–63 characters. `kind` is one of the four below.
`matches` is a list of words; the decomposer binds a tool to an agent when the
agent's clause mentions one of them, so pick words you would actually use in a
brief.

## The four kinds

| kind | what it does | must declare |
|---|---|---|
| `shell` | runs a fixed argv, no shell involved | `argv` |
| `file-read` | reads a UTF-8 file | `roots` |
| `file-write` | writes a UTF-8 file — **always destructive** | `roots` |
| `http` | one pinned request | `url` |

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

## Roots and `$VARS`

`$HOME`, `$TORNADO_VAULT` and any other environment variable expand, and `~`
works. **An unset variable fails loudly at load time** rather than silently
resolving against the working directory — `--check` will tell you.

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

## Checking your work

```sh
python3 hands.py --check     # validate every manifest and list what loaded
python3 hands.py --dry-run   # serve, but plan calls instead of executing them
```

`--dry-run` is the safe way to watch a plan come together before you let it touch
anything.
