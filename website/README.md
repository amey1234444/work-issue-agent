# Patchlane website

The product site and documentation for `github-issue-agent`, built with Astro and TypeScript. All pages are rendered to static HTML. There is no server-side agent execution, credential collection, account system, or database.

## Local development

Use Node.js 22.12+ (Node.js 24 recommended).

```bash
cd website
npm ci
npm run dev
```

Astro prints the local development URL. The development server accepts the `terminal.local` host for managed preview environments; this does not affect the production build.

## Verify and build

```bash
npm run build
npm test
```

`build` runs Astro's TypeScript/content checks and creates `dist/`. Tests validate the generated routes, local links and anchors, search, command generation, and CLI documentation coverage against the Python source. Run `npm test` after building.

For browser QA, check the home page and an article at desktop and phone widths. Exercise keyboard search (Cmd/Ctrl+K, arrows, Enter, Escape), theme persistence, both code tabs, every setup mode, code copying, mobile menus, and reduced-motion settings. The documentation sidebar and article content must remain usable without JavaScript.

## Deploy on Vercel

1. Import `amey1234444/work-issue-agent` into Vercel.
2. Select the Git branch containing this website (or merge its PR first).
3. Set **Root Directory** to `website`.
4. Set **Framework Preset** to `Astro`.
5. Use **Build Command** `npm run build`, **Output Directory** `dist`, and **Install Command** `npm ci`.
6. Select Node.js 24.x, then deploy.

No LLM or GitHub API keys are needed for this website. Vercel supplies `VERCEL_PROJECT_PRODUCTION_URL` for production canonical links. For a custom domain, set optional `SITE_URL` to the origin (for example, `https://your-domain.example`) and rebuild. Outside Vercel, set `SITE_URL` to populate the sitemap and canonical links.

`vercel.json` includes the build settings and basic response headers. Routes are real prerendered pages; do not add a catch-all SPA rewrite. A custom `404.html` is included.

## Content and design

- `src/content/docs/`: 16 Markdown guides and reference articles, including an in-depth user manual and task recipes.
- `src/pages/docs/index.astro`: documentation hub with learning paths and the complete reference directory.
- `src/pages/architecture.astro`: interactive architecture explorer and system boundaries.
- `src/scripts/architecture-data.mjs`: source-aligned educational traces for six execution scenarios.
- `src/pages/manual.md.ts`: downloadable manual generated from the same content as the web article.
- `public/examples/`: downloadable starter workflow, instructions, and YAML configuration.
- `src/content.config.ts`: schema for navigation and source links.
- `src/pages/docs/[...slug].astro`: article layout, sidebar, table of contents, previous/next navigation.
- `src/pages/search.json.ts`: static full-text index; search runs entirely in the browser.
- `src/components/WorkflowDemo.astro`: illustrated recorded workflow, with pause and reduced-motion support.
- `src/components/Setup.astro`: provider/run-mode command builder.
- `src/styles/global.css` and `src/styles/experience.css`: responsive design, light/dark themes, and architecture animations.
- `src/layouts/Base.astro`: metadata, navigation, search dialog, and footer.

Fonts are self-hosted through npm packages. The website makes no analytics requests and does not send search text or setup choices to a service. Theme preference is stored locally.

The documentation is based on the checked-in Python implementation (v0.1.0), including cases where README descriptions simplify behavior. Model defaults are documented as source defaults, not guarantees of current provider availability. The homepage workflow is an illustration of the README's recorded issue #2 / PR #3 demo; it is not a live run.

## Updating articles

Each Markdown file has `title`, `description`, `group`, `order`, and optionally `source` (a repo-relative implementation path). Add an article and rebuild: routes, search, and navigation update automatically. Check statements against the actual code and run the validation commands before submitting a PR.

## Product identity

The website is branded as **Patchlane**. The repository remains `work-issue-agent`, the Python distribution and CLI remain `github-issue-agent`, and imports remain `github_issue_agent`. This is a website rebrand; installation and backend behavior are unchanged. The reusable vector mark is in `src/components/Logo.astro` and `public/brand/patchlane-mark.svg`.
