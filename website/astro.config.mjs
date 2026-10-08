import { defineConfig } from 'astro/config';

const hostname = process.env.SITE_URL || (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : undefined);

export default defineConfig({
  site: hostname,
  output: 'static',
  trailingSlash: 'always',
  server: { host: '0.0.0.0' },
  vite: { server: { allowedHosts: ['terminal.local'] } },
  markdown: { shikiConfig: { themes: { light: 'github-light', dark: 'github-dark' }, wrap: true } },
});
