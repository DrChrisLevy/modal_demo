const slides = [...document.querySelectorAll('.deck > .slide')];
let currentSlide = 0;

function slideFromUrl() {
  const match = location.hash.match(/^#slide-(\d+)$/);
  return match ? Number(match[1]) - 1 : 0;
}

function showSlide(index) {
  if (!slides.length) return;
  currentSlide = Math.max(0, Math.min(index, slides.length - 1));
  slides.forEach((slide, slideIndex) => {
    slide.hidden = slideIndex !== currentSlide;
  });
  history.replaceState(history.state, '', `#slide-${currentSlide + 1}`);
}

showSlide(slideFromUrl());
window.addEventListener('hashchange', () => showSlide(slideFromUrl()));

let swipeStart = null;

document.addEventListener('pointerdown', event => {
  if (event.pointerType !== 'touch') return;
  swipeStart = event.isPrimary && !event.target.closest('a, button, input, textarea, select, [contenteditable]')
    ? { id: event.pointerId, x: event.clientX, y: event.clientY }
    : null;
});

document.addEventListener('pointerup', event => {
  if (event.pointerId !== swipeStart?.id) return;
  const dx = event.clientX - swipeStart.x;
  const dy = event.clientY - swipeStart.y;
  swipeStart = null;

  // Ignore taps and vertical gestures so embedded slides still allow page scrolling.
  if (Math.abs(dx) >= 40 && Math.abs(dx) > Math.abs(dy) * 1.5) {
    showSlide(currentSlide + (dx < 0 ? 1 : -1));
  }
});

document.addEventListener('pointercancel', () => { swipeStart = null; });

document.addEventListener('keydown', async event => {
  if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;

  try {
    if (event.key === 'Escape' && document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }

    if (event.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;

    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      showSlide(currentSlide + (event.key === 'ArrowRight' ? 1 : -1));
      return;
    }

    if (event.key.toLowerCase() !== 'f' || document.fullscreenElement) return;

    event.preventDefault();
    await document.documentElement.requestFullscreen();
  } catch (error) {
    console.warn('Could not change presentation fullscreen mode:', error);
  }
});
