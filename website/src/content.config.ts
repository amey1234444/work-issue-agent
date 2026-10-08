import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { glob } from 'astro/loaders';

const docs = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/docs' }),
  schema: z.object({
    title: z.string(), description: z.string(), group: z.string(), order: z.number(),
    source: z.string().default('README.md'),
  }),
});
export const collections = { docs };
