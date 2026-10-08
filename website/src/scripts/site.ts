import { searchDocs } from './search.mjs';

const toast = document.querySelector<HTMLElement>('#toast');
let toastTimer: ReturnType<typeof setTimeout>;
export function notify(message: string) {
  if (!toast) return;
  toast.textContent = message; toast.classList.add('visible');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('visible'), 2300);
}

document.querySelector('.theme-toggle')?.addEventListener('click', () => {
  const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('wia-theme', theme); } catch { /* Theme still works without storage. */ }
});

const menu = document.querySelector<HTMLElement>('#mobile-nav');
const menuButton = document.querySelector<HTMLButtonElement>('.mobile-toggle');
menuButton?.addEventListener('click', () => {
  if (!menu) return;
  menu.hidden = !menu.hidden; menuButton.setAttribute('aria-expanded', String(!menu.hidden));
});
menu?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => { menu.hidden = true; menuButton?.setAttribute('aria-expanded', 'false'); }));

async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); notify('Copied to clipboard'); }
  catch { notify('Copy unavailable. Select and copy the text manually.'); }
}
document.querySelectorAll<HTMLButtonElement>('[data-copy]').forEach(button => button.addEventListener('click', () => copyText(button.dataset.copy || '')));
document.querySelectorAll<HTMLElement>('.prose pre').forEach(pre => {
  const wrapper = document.createElement('div'); wrapper.className = 'code-wrapper';
  pre.before(wrapper); wrapper.append(pre);
  const button = document.createElement('button'); button.className = 'code-copy'; button.textContent = 'Copy'; button.setAttribute('aria-label', 'Copy code example');
  button.addEventListener('click', () => copyText(pre.querySelector('code')?.textContent || ''));
  wrapper.append(button);
});

interface SearchEntry { title: string; description: string; body: string; url: string; group: string }
const dialog = document.querySelector<HTMLDialogElement>('.search-dialog')!;
const input = document.querySelector<HTMLInputElement>('#doc-search')!;
const results = document.querySelector<HTMLElement>('.search-results')!;
let entries: SearchEntry[] | null = null;
let opener: HTMLElement | null = null;
function showResults() {
  if (!entries) return;
  results.replaceChildren();
  const matches: SearchEntry[] = searchDocs(entries, input.value);
  if (!matches.length) { const empty = document.createElement('p'); empty.className = 'search-empty'; empty.textContent = `No results for “${input.value}”. Try “token”, “workflow”, or “tests”.`; results.append(empty); return; }
  matches.forEach(entry => {
    const a = document.createElement('a'); a.href = entry.url; a.className = 'search-result';
    const group = document.createElement('span'); group.className = 'search-group'; group.textContent = entry.group;
    const title = document.createElement('strong'); title.textContent = entry.title;
    const description = document.createElement('span'); description.textContent = entry.description;
    a.append(group, title, description); results.append(a);
  });
}
async function openSearch() {
  opener = document.activeElement as HTMLElement;
  dialog.showModal(); input.focus();
  if (!entries) {
    results.textContent = 'Loading documentation…';
    try { const response = await fetch('/search.json'); if (!response.ok) throw new Error('Search failed'); entries = await response.json(); }
    catch { results.textContent = 'Search could not load. Please try again or browse the documentation.'; return; }
  }
  showResults();
}
document.querySelectorAll('[data-search-open]').forEach(button => button.addEventListener('click', openSearch));
document.querySelector('[data-search-close]')?.addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
dialog.addEventListener('close', () => opener?.focus());
input.addEventListener('input', showResults);
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if (dialog.open) dialog.close(); else openSearch(); }
  if (event.key === 'Escape' && menu && !menu.hidden) { menu.hidden = true; menuButton?.setAttribute('aria-expanded', 'false'); menuButton?.focus(); }
  if (dialog.open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    const links = Array.from(results.querySelectorAll<HTMLAnchorElement>('a'));
    const index = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (links.length) { event.preventDefault(); links[(index + (event.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length].focus(); }
  }
  if (dialog.open && event.key === 'Enter' && document.activeElement === input) results.querySelector<HTMLAnchorElement>('a')?.click();
});

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver(items => items.forEach(item => { if (item.isIntersecting) { item.target.classList.add('revealed'); observer.unobserve(item.target); } }), { threshold: 0.08 });
  document.querySelectorAll('[data-reveal]').forEach(el => { el.classList.add('will-reveal'); observer.observe(el); });
}

const tocLinks = document.querySelectorAll<HTMLAnchorElement>('.toc a');
if (tocLinks.length && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) tocLinks.forEach(link => { const active = link.hash === `#${entry.target.id}`; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current'); });
  }), { rootMargin: '-90px 0px -65% 0px' });
  document.querySelectorAll('.prose h2').forEach(h => observer.observe(h));
}
