---
title: freeai — free NVIDIA NIM model CLI
tags: [tooling, ai, nvidia-nim]
status: active
source: ~/.local/bin/freeai
---

> [!info] Mirrors the script at `~/.local/bin/freeai`.

A zero-dependency Python CLI that calls free models on NVIDIA NIM (`https://integrate.api.nvidia.com/v1`, OpenAI-compatible). Claude Code can shell out to it for cheap or bulk calls, e.g. transcript analysis for [[clip-factory]].

## Setup (one time)
Add the key to `~/.hermes/.env` as `NVIDIA_API_KEY=nvapi-...`. You can get one free at build.nvidia.com.

> [!warning] Never paste the key into this vault. It syncs to iCloud.

## Usage
- `freeai "prompt"`
- `cat file.txt | freeai "instruction"`
- `freeai -m <model> "prompt"` (default is `deepseek-ai/deepseek-v4-flash-0731`)
- `freeai --models` lists the catalogue
- `-s` sets a system prompt, `--json` prints the raw response

When the free tier rate-limits or returns `529 Overloaded`, the script retries up to 5 times with exponential backoff.
