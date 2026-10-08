import { getEntry } from 'astro:content';
export async function GET() {
  const entry = await getEntry('docs', 'manual');
  if (!entry) throw new Error('User manual is missing');
  return new Response(`# ${entry.data.title}\n\n${entry.data.description}\n\n${entry.body}`, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } });
}
