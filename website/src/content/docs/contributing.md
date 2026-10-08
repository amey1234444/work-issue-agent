---
title: Contributing
description: Work on the agent or improve its documentation.
group: Operate and extend
order: 14
source: AGENTS.md
---

Patchlane is MIT licensed. Start with a focused issue or pull request that explains the problem and the expected behavior.

## Development setup

```bash
git clone https://github.com/amey1234444/work-issue-agent.git
cd work-issue-agent
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,all]"
```

## Repository conventions

Use Python 3.10+ and modern typing. Keep changes focused, add or update tests for behavior changes, and do not hand-edit generated files. Follow the repository's `AGENTS.md` and relevant `.ai/rules/`.

## Verification

```bash
pytest -q
ruff check .
mypy github_issue_agent
```

Include meaningful verification results in your PR. Reference the related issue when there is one.

## Website development

The product and documentation site is a static Astro project in `website/`. It uses local fonts, Markdown content collections, and small browser scripts for search, tabs, theme, and navigation.

```bash
cd website
npm ci
npm run dev
```

Edit articles in `src/content/docs/`. Each article has a title, description, navigation group, order, and optional source path. The sidebar and search index are built from this collection.

```bash
npm run build
npm test
```

The checks validate types, static routes, local links, documentation coverage, and source-aligned CLI options. See `website/README.md` for optional browser checks and deployment.

## Deploy the website on Vercel

Import this GitHub repository, select the branch containing the website, and set **Root Directory** to `website`. Use the Astro preset, build command `npm run build`, and output directory `dist`.

The website needs no agent API keys. Optionally set `SITE_URL` to your final production origin for canonical URLs and the sitemap; on Vercel, the project production URL is used as a fallback.

This deploys the documentation website. The Python agent continues to run in a user's own environment.
