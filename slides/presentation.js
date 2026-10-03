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

const interactiveElements = 'a, button, input, textarea, select, [contenteditable]';
let pointerStart = null;
let suppressClick = false;

document.addEventListener('pointerdown', event => {
  suppressClick = !event.isPrimary || Boolean(event.target.closest(interactiveElements));
  pointerStart = !suppressClick
    ? { id: event.pointerId, x: event.clientX, y: event.clientY }
    : null;
});

document.addEventListener('pointerup', event => {
  if (event.pointerId !== pointerStart?.id) return;
  const dx = event.clientX - pointerStart.x;
  const dy = event.clientY - pointerStart.y;
  pointerStart = null;
  // A drag or swipe must not also advance through the browser's follow-up click.
  suppressClick = Math.max(Math.abs(dx), Math.abs(dy)) > 10;

  // Ignore taps and vertical gestures so embedded slides still allow page scrolling.
  if (event.pointerType === 'touch' && Math.abs(dx) >= 40 && Math.abs(dx) > Math.abs(dy) * 1.5) {
    showSlide(currentSlide + (dx < 0 ? 1 : -1));
  }
});

document.addEventListener('pointercancel', () => {
  pointerStart = null;
  suppressClick = true;
});

document.addEventListener('click', event => {
  if (suppressClick || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
  if (event.target.closest(interactiveElements) || !window.getSelection().isCollapsed) return;
  showSlide(currentSlide + 1);
});

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
