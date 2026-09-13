# Obsidian Vault Guidelines & Context

## Core Vault Structure
- `/Daily Notes` : Chronological daily logs (`YYYY-MM-DD.md`).
- `/Projects`    : Active projects and deliverable specifications.
- `/Knowledge`   : Evergreen topic notes, summaries, and reference material.
- `/Templates`   : Templater templates (do NOT edit directly during note creation).
- `/Archive`     : Inactive or completed projects.

> [!note] Current state
> These folders are the target convention, not yet the reality. Today the vault is flat at the
> root (`clip-factory.md`, `ink-sky.md`, `2026-08-30.md`, …) plus an `Imported/` folder.
> Create a folder the first time a note genuinely belongs in it; do not bulk-reorganise
> existing notes without being asked, and never break existing `[[wikilinks]]` while moving.

## Note Creation & Formatting Conventions
- **Note Titles**: Use sentence case for titles (e.g., `Database scaling strategies.md`).
- **Internal Links (Wikilinks)**: Always link related concepts using `[[Note Title]]` or `[[Note Title|Custom Display Text]]`.
- **Headers**: Start with a `# Title` header matching the filename, followed by `## Subheadings`.
- **Callouts**: Use Obsidian callouts for highlights, warnings, and tips:
  ```markdown
  > [!NOTE] Key Takeaway
  > Brief summary of the concept.
  ```

## YAML Frontmatter Schema
Every new note created in `/Knowledge` or `/Projects` must include YAML frontmatter at the very top:

```yaml
---
title: Note Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [type/knowledge, status/draft]
aliases: []
---
```

## Common Tag Conventions
- Note types: `type/knowledge`, `type/project`, `type/daily`, `type/meeting`
- Note status: `status/draft`, `status/active`, `status/completed`, `status/archived`

## Plugin-Specific Syntax Rules
- **Dataview**: Use Dataview code blocks for dynamic queries:

  ````markdown
  ```dataview
  LIST FROM #type/project WHERE status = "active"
  ```
  ````

- **Tasks**: Tasks should use standard Markdown checkboxes with optional completion dates:
  `- [ ] Task description [due:: YYYY-MM-DD]`

## Hard Constraints
- **Preserve Existing Frontmatter**: When modifying existing notes, never overwrite or strip existing YAML tags or aliases.
- **Do Not Modify Templates**: Leave files in `/Templates/` unchanged unless explicitly asked to update a template.
- **Link Preservation**: Never delete or break existing `[[Wikilinks]]` during note refactoring.
- **No Secrets**: This vault syncs to iCloud. Never write API keys, tokens, or credentials into a note — reference the path where the credential lives, never the value.
