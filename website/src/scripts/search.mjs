/** Search titles first, then descriptions and full article text. */
export function searchDocs(entries, query) {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return entries.slice(0, 6);
  return entries.map(entry => {
    const title = entry.title.toLowerCase();
    const description = entry.description.toLowerCase();
    const body = entry.body.toLowerCase();
    const all = `${title} ${description} ${body}`;
    if (!words.every(word => all.includes(word))) return { entry, score: 0 };
    return { entry, score: words.reduce((score, word) => score + (title.includes(word) ? 10 : description.includes(word) ? 5 : 1), 0) };
  }).filter(item => item.score > 0).sort((a, b) => b.score - a.score).slice(0, 12).map(item => item.entry);
}
