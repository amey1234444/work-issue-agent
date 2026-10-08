import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
export const GET: APIRoute = async ({ site }) => {
  const paths = ['/', ...(await getCollection('docs')).map(doc => `/docs/${doc.id}/`)];
  return new Response(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${site ? paths.map(path => `<url><loc>${new URL(path, site)}</loc></url>`).join('') : ''}</urlset>`, { headers: { 'Content-Type': 'application/xml' } });
};
