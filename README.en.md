<p align="center">
  <img src="assets/banner.png" alt="directors-book: an agent skill for Seedance video generation" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-5.0.0-2563eb" alt="version 5.0.0">
  <img src="https://img.shields.io/badge/stages-screenplay%20%7C%20storyboard%20%7C%20assets%20%7C%20video%20prompts-7c3aed" alt="four stages, each usable alone">
  <img src="https://img.shields.io/badge/output-HTML%20director%27s%20book-ef4444" alt="output: HTML director's book">
  <img src="https://img.shields.io/badge/model-Seedance%202.0%20%7C%202.5-0d9488" alt="model: Seedance 2.0 and 2.5">
  <img src="https://img.shields.io/badge/genre-short%20drama%20%7C%20film-f59e0b" alt="genre: short drama, film">
  <img src="https://img.shields.io/badge/tested%20on-Claude%20Code%20%7C%20Codex%20%7C%20WorkBuddy-16a34a" alt="tested on Claude Code, Codex, WorkBuddy">
  <img src="https://img.shields.io/badge/license-MIT-eab308" alt="MIT License">
</p>

<p align="center"><a href="README.md">简体中文</a> · <b>English</b></p>

> **Version 5.0.0.** The version number continues the earlier directors-book line (the old 2.0.1, no longer maintained): same name and a similar structure, but the content was rewritten and is not compatible with the old version. All the skill files are written, and it has been tried in Claude Code, Codex, and WorkBuddy (short drama and film; a few runs were contaminated, see `tests/`). Most of the writing rules have not been compared in controlled experiments; see Known limitations below.

`directors-book` (导演手册, "Director's Book") is an agent skill for Seedance video generation. It helps you turn an idea, step by step, into a screenplay, a storyboard, character and scene asset prompts, and video prompts, and can assemble everything into a single HTML "director's book" with one-click copy buttons.

## What it does

Four stages, each usable on its own:

1. **Screenplay**: two kinds, short drama or film (it asks which one first).
2. **Storyboard**: a shot overview table (close to an industry shot list), shot descriptions, splitting into generation clips, and a check for shots that should be merged.
3. **Asset pack**: character prompts (a four-view sheet: three views plus a face close-up) and scene prompts (master image, multi-camera grid, blocking map).
4. **Video prompts**: overall concept, reference binding, shots, sound, negative constraints.

There is also one more option, the **director's book**: all four stages together, delivered as one HTML file with a fixed layout (screenplay, storyboard, asset prompts, and video prompts; the video prompts come last, one per segment, all copyable with one click).

Before starting, it asks for the **genre** (short drama or film, even if you bring a script), the **aspect ratio**, and the **model version** (Seedance 2.0 or 2.5), depending on the task; agents with a pop-up question tool use it. After the screenplay and storyboard are confirmed, it asks whether you want the director's book or just the prompts.

## Installation

This skill follows the [Agent Skills open standard](https://agentskills.io/specification) and works with both Claude Code and Codex.

**Option 1: install with a command**

```bash
npx skills add Jay-make8/directors-book
```

This command comes from the third-party [skills](https://github.com/vercel-labs/skills) tool. It finds `directors-book` in this repository and installs it into the agents you choose; add `-g` to install at user level, and `-a` to pick agents. We verified that it discovers this skill in the repository; actual installation was not checked in every agent.

**Option 2: copy it manually**

Download the zip from the [Releases](https://github.com/Jay-make8/directors-book/releases) page (or clone this repository) and copy the `directors-book` folder to:

| agent | user level (all projects) | project level |
|---|---|---|
| Claude Code | `~/.claude/skills/directors-book/` | `<project>/.claude/skills/directors-book/` |
| Codex | `~/.agents/skills/directors-book/` | `<project>/.agents/skills/directors-book/` |

Paths come from each vendor's documentation and may change; follow the official docs:
- Claude Code: <https://code.claude.com/docs/en/skills>
- Codex: <https://learn.chatgpt.com/docs/build-skills>

Restart your session after installing.

## Usage

Just describe what you need, for example:

- "Write a short-drama script for me"
- "Split this script into a storyboard"
- "Make asset prompts for this character"
- "Generate the director's book"

## Repository layout

```
directors-book-repo/
├── skills/directors-book/     the skill itself
│   ├── SKILL.md               entry point: four stages, hard rules, routing
│   ├── references/            rules read on demand (script, storyboard, assets, video prompt, checklist...)
│   ├── examples/              examples, including a sample handbook.json
│   ├── assets/                HTML template for the director's book
│   └── scripts/               build_handbook.py: generates the HTML
├── tests/                     manual test plan and run notes
├── README.md / README.en.md
├── ACKNOWLEDGEMENTS.md
├── CHANGELOG.md
└── LICENSE
```

## Known limitations

- Generating the director's book HTML needs `python3` (3.8 or newer, standard library only). If the agent cannot run commands, it falls back to a Markdown file with the same structure and tells you that no HTML was generated.
- Most of the writing rules come from studying other skills and tutorials, plus feedback from real generations. **Most have not been tested in controlled comparisons**, and results vary by model and platform.
- Duration and image-count numbers for Seedance 2.0 and 2.5 come from third-party sources; there is no official ByteDance page. They are defaults that you can override for your platform.
- There is no single official figure for the prompt length limit; sources disagree.

## License

[MIT](LICENSE)

## Acknowledgements

This project borrows ideas from many people; see [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
