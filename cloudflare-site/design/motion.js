const clips = [...document.querySelectorAll('.hero-media video')];
const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
let wantsMotion = !preference.matches;
let visible = true;
let active = 0;
let switching = false;

function sync() {
  const play = wantsMotion && visible && !document.hidden;
  clips.forEach((video, index) => {
    if (index === active && play) {
      video.muted = true;
      video.play().catch(error => {
        // Pausing offscreen can cancel a pending play; allow it to resume later.
        if (index === active && error.name !== 'AbortError') wantsMotion = false;
      });
    } else video.pause();
  });
}

async function advance() {
  if (switching) return;
  switching = true;
  const previous = active;
  const index = (active + 1) % clips.length;
  const next = clips[index];
  try {
    if (next.readyState < 2) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { cleanup(); reject(new Error('Clip timed out')); }, 12000);
        const cleanup = () => { clearTimeout(timer); next.removeEventListener('loadeddata', ready); next.removeEventListener('error', failed); };
        const ready = () => { cleanup(); resolve(); };
        const failed = () => { cleanup(); reject(new Error('Clip unavailable')); };
        next.addEventListener('loadeddata', ready, {once:true});
        next.addEventListener('error', failed, {once:true});
        next.load();
      });
    }
    next.currentTime = 0;
    active = index;
    next.classList.add('is-active');
    clips[previous].classList.remove('is-active');
    sync();
  } catch {
    // Keep the current scene available if the next file cannot load.
    clips[previous].currentTime = 0;
    sync();
  } finally {
    switching = false;
  }
}

clips.forEach((video, index) => video.addEventListener('ended', () => {
  if (index === active && wantsMotion && visible && !document.hidden) advance();
}));
document.addEventListener('visibilitychange', sync);
preference.addEventListener('change', event => { wantsMotion = !event.matches; sync(); });
if ('IntersectionObserver' in window) {
  new IntersectionObserver(entries => { visible = entries[0].isIntersecting; sync(); }, {threshold:0.05})
    .observe(document.querySelector('.hero'));
}
sync();
