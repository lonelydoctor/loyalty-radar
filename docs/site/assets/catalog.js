(() => {
  const cards = [...document.querySelectorAll('.source-card')];
  const search = document.querySelector('#source-search');
  const pack = document.querySelector('#source-pack');
  const method = document.querySelector('#source-method');
  const priority = document.querySelector('#source-priority');
  if (!cards.length || !search || !pack || !method || !priority) return;
  const apply = () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      card.hidden = Boolean(
        (query && !card.dataset.search.includes(query)) ||
        (pack.value !== 'all' && card.dataset.pack !== pack.value) ||
        (method.value !== 'all' && card.dataset.method !== method.value) ||
        (priority.value !== 'all' && card.dataset.priority !== priority.value)
      );
      if (!card.hidden) visible += 1;
    });
    document.querySelector('#visible-source-count').textContent = String(visible);
    document.querySelector('#catalog-empty').classList.toggle('visible', visible === 0);
  };
  search.addEventListener('input', apply);
  [pack, method, priority].forEach((control) => control.addEventListener('change', apply));
  document.querySelectorAll('[data-pack-button]').forEach((button) => button.addEventListener('click', () => {
    pack.value = button.dataset.packButton;
    apply();
    document.querySelector('.catalog-controls').scrollIntoView({behavior: 'smooth'});
  }));
  apply();
})();
