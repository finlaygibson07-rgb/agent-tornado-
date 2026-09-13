---
title: Vault backup
created: 2026-09-13
updated: 2026-09-13
tags: [type/knowledge, status/active, tooling, git]
aliases: [obsidian-backup]
source: ~/.local/bin/obsidian-backup.sh
---

# Vault backup

> [!info] Mirrors the script at `~/.local/bin/obsidian-backup.sh`.

This vault is a git repo. `obsidian-backup.sh` stages everything, makes one timestamped
commit describing the change counts (`+2 ~5 -1`), and pushes if an `origin` remote exists.

## Run it

```bash
~/.local/bin/obsidian-backup.sh       # commit (and push if a remote is set)
~/.local/bin/obsidian-backup.sh -n    # dry run — show what would be committed
```

Exits quietly with `no changes` when nothing moved, so it is safe on a timer.

## Guards
- **Single instance** — a lock file stops overlapping runs from corrupting the index.
- **iCloud placeholders** — aborts if any `*.icloud` stub is present, because committing
  then would record the real file as deleted.
- **Push failure is non-fatal to your data** — the commit is already local; only the push
  is lost, and the next run retries.

## Not yet done
- [ ] No `origin` remote. Commits are local-only until a **private** GitHub repo is added.
- [ ] No schedule. Options below.

## Scheduling
Cron under macOS needs Full Disk Access granted to `/usr/sbin/cron` to read
`~/Library/Mobile Documents`, or every run fails silently:

```
0 * * * * $HOME/.local/bin/obsidian-backup.sh >> /tmp/obsidian-backup.log 2>&1
```

The **Obsidian Git** community plugin is the lower-friction alternative — it commits on an
interval from inside Obsidian, with no Full Disk Access grant and no risk of committing
mid-write while a note is open.

> [!warning] Never commit secrets
> This vault syncs to iCloud *and* would sync to GitHub. Reference credential paths, never
> values. See [[CLAUDE]].

Related: [[freeai]], [[MCP Loader]].
