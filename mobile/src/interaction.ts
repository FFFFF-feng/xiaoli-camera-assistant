import { onBeforeUnmount, onMounted, type Ref } from 'vue';

/** One delegated listener, one frame per pointer update; touch never needs a hover. */
export function useTactileSurfaces(root: Ref<HTMLElement | undefined>) {
  let frame = 0;
  let active: HTMLElement | null = null;
  let x = 0;
  let y = 0;
  let bounds: DOMRect | undefined;
  const selector = '.primary, .camera-button, .secondary, .hero-link, .prompt-chips button, .bottom-nav button, .hero-portrait';
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function reset() {
    cancelAnimationFrame(frame);
    frame = 0;
    if (active) {
      active.removeAttribute('data-lit');
      for (const key of ['--light-x', '--light-y', '--tilt-x', '--tilt-y']) active.style.removeProperty(key);
    }
    active = null;
    bounds = undefined;
  }
  function move(event: PointerEvent) {
    if (!finePointer.matches || reducedMotion.matches || event.pointerType === 'touch') return;
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>(selector) : null;
    if (!target || target.matches(':disabled, .disabled') || target.closest('fieldset:disabled')) { reset(); return; }
    if (target !== active) {
      reset();
      active = target;
      bounds = target.getBoundingClientRect();
      active.dataset.lit = '';
    }
    x = event.clientX;
    y = event.clientY;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!active || !bounds) return;
      const px = Math.max(0, Math.min(1, (x - bounds.left) / bounds.width));
      const py = Math.max(0, Math.min(1, (y - bounds.top) / bounds.height));
      active.style.setProperty('--light-x', `${(px * 100).toFixed(1)}%`);
      active.style.setProperty('--light-y', `${(py * 100).toFixed(1)}%`);
      active.style.setProperty('--tilt-x', `${((.5 - py) * 3).toFixed(2)}deg`);
      active.style.setProperty('--tilt-y', `${((px - .5) * 4).toFixed(2)}deg`);
    });
  }
  function preferencesChanged() { reset(); }
  onMounted(() => {
    root.value?.addEventListener('pointermove', move, { passive: true });
    root.value?.addEventListener('pointerleave', reset);
    window.addEventListener('scroll', reset, { passive: true });
    reducedMotion.addEventListener('change', preferencesChanged);
    finePointer.addEventListener('change', preferencesChanged);
  });
  onBeforeUnmount(() => {
    reset();
    root.value?.removeEventListener('pointermove', move);
    root.value?.removeEventListener('pointerleave', reset);
    window.removeEventListener('scroll', reset);
    reducedMotion.removeEventListener('change', preferencesChanged);
    finePointer.removeEventListener('change', preferencesChanged);
  });
}

/** Native snapshots keep header/navigation stable while the content opens like an iris. */
export function createSceneTransition() {
  let revision = 0;
  let active: ViewTransition | undefined;
  let fallback: Animation | undefined;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function change(update: () => Promise<void>, target: () => HTMLElement | undefined) {
    const current = ++revision;
    active?.skipTransition();
    fallback?.cancel();
    const apply = async () => { if (current === revision) await update(); };
    const surface = target();
    // Observable DOM state for browser QA, without exposing diagnostics in the interface.
    const phase = (value: string) => { if (surface && current === revision) surface.dataset.motionState = value; };
    if (reducedMotion.matches || document.visibilityState !== 'visible') {
      if (surface) surface.dataset.motionEngine = reducedMotion.matches ? 'reduced' : 'hidden';
      phase('idle');
      void apply();
      return;
    }
    if (typeof document.startViewTransition === 'function') {
      if (surface) surface.dataset.motionEngine = 'native';
      phase('capturing');
      const transition = document.startViewTransition(apply);
      active = transition;
      // Hidden tabs and interrupted transitions legitimately skip their animation.
      void transition.ready.then(() => phase('animating')).catch(() => {});
      void transition.finished.catch(() => {}).finally(() => { phase('idle'); if (active === transition) active = undefined; });
    } else {
      if (surface) surface.dataset.motionEngine = 'fallback';
      void apply().then(() => {
        if (current !== revision) return;
        fallback = target()?.animate([
          { opacity: 0, transform: 'translateY(10px)' },
          { opacity: 1, transform: 'translateY(0)' },
        ], { duration: 260, easing: 'cubic-bezier(.22, 1, .36, 1)' });
        phase('animating');
        void fallback?.finished.catch(() => {}).finally(() => phase('idle'));
      });
    }
  }
  function stop() { active?.skipTransition(); fallback?.cancel(); }
  reducedMotion.addEventListener('change', stop);
  onBeforeUnmount(() => { revision++; stop(); reducedMotion.removeEventListener('change', stop); });
  return change;
}
