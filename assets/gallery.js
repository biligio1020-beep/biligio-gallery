// Filter only cards on this page; no personal data or external requests.
(() => {
  const filters = [...document.querySelectorAll('[data-filter]')];
  const cards = [...document.querySelectorAll('[data-category]')];
  if (!filters.length) return;
  for (const button of filters) {
    button.addEventListener('click', () => {
      const selected = button.dataset.filter;
      for (const el of filters) {
        el.classList.toggle('active', el === button);
        el.setAttribute('aria-pressed', String(el === button));
      }
      for (const card of cards) card.classList.toggle('hidden', selected !== 'all' && card.dataset.category !== selected);
    });
  }
})();
