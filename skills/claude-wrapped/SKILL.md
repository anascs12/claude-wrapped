---
name: claude-wrapped
description: >-
  Generate a Spotify-Wrapped-style "year in review" of the user's Claude Code
  usage as a shareable HTML page. Use when the user asks for their Claude
  Wrapped, Claude stats, usage recap, year in review, or "wrapped". Reads only
  the local ~/.claude/projects logs; nothing is uploaded.
---

# Claude Wrapped

Turn the user's local Claude Code history into a shareable, Spotify-Wrapped-style
stats page: a vertical scroll of bold cards with their biggest numbers, a fun
"persona", when-they-work charts, top tools, and top projects.

## How it works

All data comes from `~/.claude/projects/*/*.jsonl`, which Claude Code writes to
disk on this machine. The script never makes a network request and never uploads
anything. The only external resource is a Google Fonts link inside the generated
HTML, loaded when the user opens the page in their browser.

## Running it

```bash
python3 scripts/wrapped.py --open
```

Options:
- `--out FILE`      where to save the page (default `claude-wrapped.html`)
- `--projects DIR`  override the history location (default `~/.claude/projects`)
- `--open`          open the result in the default browser when done

Requires only Python 3.8+ (standard library, no pip installs).

## What to tell the user

1. Run the command above for them (or tell them to run it).
2. Point them to the saved `claude-wrapped.html` and tell them to open it.
3. The **last card** is the summary — tell them to screenshot it to share.

## Notes

- Timestamps are converted to the machine's local timezone, so "peak hour"
  reflects when the user actually works.
- Token and "words written" figures are estimates from the logged usage counts.
- If no history exists yet, the script exits with a friendly message.
