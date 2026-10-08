import { getCollection } from 'astro:content';
export async function GET() {
  const docs = (await getCollection('docs')).sort((a, b) => a.data.order - b.data.order);
  return new Response(JSON.stringify(docs.map(doc => ({ title: doc.data.title, description: doc.data.description, group: doc.data.group, url: `/docs/${doc.id}/`, body: doc.body || '' }))), { headers: { 'Content-Type': 'application/json' } });
}
