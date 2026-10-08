// Inspirace carousel.
// - Arrow buttons scroll by one card and hide at each end.
// - Cards only partly in view get a lower --focus, which CSS turns into blur and fade.
// - Clicking a blurred card brings it into view instead of opening it.
// Swiping, trackpad and keyboard scrolling are native browser behaviour.
document.querySelectorAll('[data-carousel]').forEach((carousel) => {
  const track = carousel.querySelector('.carousel-track');
  const cards = [...track.querySelectorAll('.post-card')];
  const prev = carousel.querySelector('[data-dir="-1"]');
  const next = carousel.querySelector('[data-dir="1"]');

  const step = () => {
    const card = cards[0];
    const gap = parseFloat(getComputedStyle(track).columnGap) || 0;
    return card ? card.getBoundingClientRect().width + gap : track.clientWidth * 0.8;
  };

  const updateButtons = () => {
    const max = track.scrollWidth - track.clientWidth;
    carousel.classList.toggle('no-overflow', max <= 2);
    prev.disabled = track.scrollLeft <= 2;
    next.disabled = track.scrollLeft >= max - 2;
  };

  // The "in focus" zone is the text column, not the whole screen width.
  const focusZone = () => {
    const r = carousel.getBoundingClientRect();
    return { left: r.left - 1, right: r.right + 1 };
  };

  const updateFocus = () => {
    const zone = focusZone();
    cards.forEach((card) => {
      const r = card.getBoundingClientRect();
      const visible = Math.max(0, Math.min(r.right, zone.right) - Math.max(r.left, zone.left));
      const ratio = r.width ? visible / r.width : 1;
      card.style.setProperty('--focus', Math.min(1, ratio * 1.15).toFixed(2));
      card.classList.toggle('is-peek', ratio < 0.9);
    });
  };

  let frame = 0;
  const onScroll = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; updateButtons(); updateFocus(); });
  };

  prev.addEventListener('click', () => track.scrollBy({ left: -step(), behavior: 'smooth' }));
  next.addEventListener('click', () => track.scrollBy({ left: step(), behavior: 'smooth' }));

  cards.forEach((card) => {
    card.addEventListener('click', (event) => {
      if (!card.classList.contains('is-peek')) return;
      event.preventDefault();
      card.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' });
    });
  });

  track.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  updateButtons();
  updateFocus();
});
