/** Shared, interruptible motion. Content and ARIA state always update immediately. */
export function createContentMotion(preference) {
  const running = new Set();
  const byElement = new WeakMap();
  preference.addEventListener('change', () => {
    if (preference.matches) [...running].forEach(animation => animation.cancel());
  });
  return (elements, direction = 1) => {
    for (const element of elements) {
      if (!element) continue;
      byElement.get(element)?.cancel();
      if (preference.matches || typeof element.animate !== 'function') continue;
      const animation = element.animate([
        { opacity: 0.35, transform: `translateX(${direction * 12}px)` },
        { opacity: 1, transform: 'translateX(0)' },
      ], { duration: 280, easing: 'cubic-bezier(.22,1,.36,1)' });
      running.add(animation); byElement.set(element, animation);
      const cleanup = () => {
        running.delete(animation);
        if (byElement.get(element) === animation) byElement.delete(element);
      };
      animation.onfinish = cleanup; animation.oncancel = cleanup;
    }
  };
}

const animate = typeof window === 'undefined' ? () => {} : createContentMotion(window.matchMedia('(prefers-reduced-motion: reduce)'));
export const animateContent = (elements, direction = 1) => animate(elements, direction);

/** One moving indicator follows the actual tab geometry, including font/viewport changes. */
export function installTabIndicator(list) {
  const marker = document.createElement('span');
  marker.className = 'tab-indicator'; marker.setAttribute('aria-hidden', 'true');
  list.append(marker); list.classList.add('has-tab-motion');
  const move = () => {
    const tab = list.querySelector('[role="tab"][aria-selected="true"]');
    if (!tab) return;
    const parent = list.getBoundingClientRect(), child = tab.getBoundingClientRect();
    marker.style.width = `${child.width}px`;
    marker.style.height = `${child.height}px`;
    marker.style.transform = `translate(${child.left - parent.left - list.clientLeft}px,${child.top - parent.top - list.clientTop}px)`;
  };
  move();
  requestAnimationFrame(() => list.classList.add('tab-motion-ready'));
  const observer = new ResizeObserver(move);
  observer.observe(list);
  list.querySelectorAll('[role="tab"]').forEach(tab => observer.observe(tab));
  document.fonts.ready.then(move);
  return move;
}

export function nextTabIndex(key, index, count) {
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  if (key === 'ArrowRight') return (index + 1) % count;
  if (key === 'ArrowLeft') return (index - 1 + count) % count;
  return null;
}
