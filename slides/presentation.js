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
