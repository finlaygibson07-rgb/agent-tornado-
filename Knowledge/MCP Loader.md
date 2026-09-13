---
type: tool
created: 2026-09-03
tags: [mcp, claude-code, hermes, tooling]
artifact: https://claude.ai/code/artifact/3fd45beb-cd58-4e08-b80e-d3dfbd43e2c6
---

# MCP Loader

A single-page "patch bay" for Model Context Protocol servers. Pick modules, fill in
their real parameters, and copy the exact thing to run. Grew out of
`~/mcp-drop-box.html` (a static mockup) — this version actually generates config.

- **Live artifact:** <https://claude.ai/code/artifact/3fd45beb-cd58-4e08-b80e-d3dfbd43e2c6>
- **Local copy:** [[MCP Loader.html]] — self-contained, open in any browser (needs
  internet once for the IBM Plex webfont; works offline otherwise)
- **Artifact source:** `/private/tmp/.../scratchpad/mcp-loader.html` (this session) —
  redeploy that path to update the artifact URL

A sandboxed web page can't shell out, so it's a **config composer**, not an installer:
assemble a loadout → it emits the command / JSON / Hermes lines you paste yourself.

## How it works

- **Catalog** (left) — draggable server cards, or press `+`. Each shows its package, a
  transport chip, and a `key` flag when it needs a secret.
- **The bay** (right) — each patched module is a card with a transport-coloured cable
  stripe (amber `stdio` / cyan `sse` / violet `http`), an editable server key, and
  inline fields for its parameters. Empty secret fields show a rust outline and become
  `<PLACEHOLDER>` tokens in the output.
- **Custom module** — for anything not in the catalog: stdio (command / args / env) or a
  remote URL with headers.
- **Install** (bottom) — live, copyable output in three formats:
  - **CLI** — `claude mcp add <key> -e KEY=VAL -- npx -y …` (and
    `--transport http … --header …` for remotes)
  - **JSON** — `{ "mcpServers": { … } }` for `.mcp.json` (project) or
    `claude_desktop_config.json` (Claude Desktop)
  - **Hermes** — `python3 ~/.hermes/scripts/install-mcp-server.py <key>` per module,
    then restart Hermes
- Loadout persists to `localStorage`. Secrets are **not** stored unless you tick
  "remember secrets in this browser". Nothing is ever sent anywhere.
- Opens with a sample loadout (filesystem + github) already patched.

## Catalog

| module | transport | package | needs a key |
|---|---|---|---|
| filesystem | stdio | `@modelcontextprotocol/server-filesystem` | — |
| github | stdio | `@modelcontextprotocol/server-github` | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| git | stdio | `mcp-server-git` (uvx) | — |
| memory | stdio | `@modelcontextprotocol/server-memory` | — |
| fetch | stdio | `mcp-server-fetch` (uvx) | — |
| sequential-thinking | stdio | `@modelcontextprotocol/server-sequential-thinking` | — |
| time | stdio | `mcp-server-time` (uvx) | — |
| sqlite | stdio | `mcp-server-sqlite` (uvx) | — |
| postgres | stdio | `@modelcontextprotocol/server-postgres` | connection URL |
| puppeteer | stdio | `@modelcontextprotocol/server-puppeteer` | — |
| playwright | stdio | `@playwright/mcp@latest` | — |
| brave-search | stdio | `@modelcontextprotocol/server-brave-search` | `BRAVE_API_KEY` |
| slack | stdio | `@modelcontextprotocol/server-slack` | `SLACK_BOT_TOKEN` |
| notion | stdio | `@notionhq/notion-mcp-server` | `NOTION_TOKEN` |
| github (remote) | http | `https://api.githubcopilot.com/mcp/` | PAT (Bearer) |
| context7 | http | `https://mcp.context7.com/mcp` | — |

> Commands are templates — confirm each package name and its args against the server's
> own README for the version you're installing. Some `@modelcontextprotocol/server-*`
> packages have moved or been archived.

## To extend

Edit the `CATALOG` array near the top of the `<script>` in [[MCP Loader.html]] (or the
artifact source). Each entry:

```js
{ id:"name", transport:"stdio"|"http"|"sse", pkg:"display string", desc:"one line",
  command:"npx", args:["-y","pkg","{fieldKey}"],           // stdio
  url:"https://…",                                          // remote
  fields:[
    { key:"path", label:"Allowed path", def:"/Users/you/x" },        // arg token {path}
    { key:"API_KEY", label:"API_KEY", env:true, secret:true },       // -e / env{}
    { key:"token", label:"Token", header:"Authorization",
      headerPrefix:"Bearer ", secret:true }                          // remote header
  ] }
```

## Related

- [[clip-factory]] — other Hermes-adjacent tooling
