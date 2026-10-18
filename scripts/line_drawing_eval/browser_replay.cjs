/* Offline browser replay check. Opens the static gallery, aborts every non-GET
   and every non-local request, then probes two analysis POSTs to prove the
   interception actually blocks them. Writes metrics and screenshots. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/丁铭哲/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const url = argument('url');
const out = path.resolve(argument('out', path.join(process.cwd(), 'replay')));
if (!url || !/^http:\/\/127\.0\.0\.1:\d+\//.test(url)) {
  throw new Error('Pass --url http://127.0.0.1:<port>/gallery.html');
}
fs.mkdirSync(out, { recursive: true });
const origin = new URL(url).origin;
const metrics = {
  kind: 'offline_browser_replay_check',
  url,
  started_at: new Date().toISOString(),
  actual_analysis_posts: 0,
  blocked_posts: [],
  blocked_external_requests: [],
  blocked_non_get: [],
  page_errors: [],
  console_errors: [],
  screenshots: [],
  viewports: [],
};

async function instrument(context, label) {
  const page = await context.newPage();
  page.on('pageerror', error => metrics.page_errors.push({ label, message: String(error) }));
  page.on('console', message => {
    if (message.type() === 'error') metrics.console_errors.push({ label, text: message.text() });
  });
  await context.route('**/*', async route => {
    const request = route.request();
    const target = request.url();
    if (target.startsWith('data:') || target.startsWith('blob:')) return route.continue();
    if (!target.startsWith(origin + '/')) {
      metrics.blocked_external_requests.push({ label, url: target, method: request.method() });
      return route.abort();
    }
    if (request.method() !== 'GET' && request.method() !== 'HEAD') {
      metrics.blocked_posts.push({ label, url: target, method: request.method() });
      return route.abort();
    }
    return route.continue();
  });
  return page;
}

(async () => {
  // Use the locally installed Chrome; no browser download is needed or attempted.
  const browser = await chromium.launch({
    headless: true,
    executablePath: argument('chrome', 'C:/Program Files/Google/Chrome/Application/chrome.exe'),
  });
  try {
    for (const [label, viewport] of [['desktop', { width: 1280, height: 900 }],
                                     ['mobile390', { width: 390, height: 844 }]]) {
      const context = await browser.newContext({
        viewport, serviceWorkers: 'block', reducedMotion: 'reduce',
      });
      const page = await instrument(context, label);
      await page.goto(url, { waitUntil: 'load' });
      await page.waitForFunction(() => Array.from(document.images).every(image => image.complete));
      const audit = await page.evaluate(() => ({
        scripts: document.querySelectorAll('script').length,
        forms: document.querySelectorAll('form').length,
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
        images: Array.from(document.images).map(image => ({
          src: image.currentSrc, complete: image.complete, width: image.naturalWidth,
        })),
        cards: document.querySelectorAll('section.card').length,
      }));
      metrics.viewports.push({ label, ...audit });
      const shot = path.join(out, `gallery-${label}.png`);
      await page.screenshot({ path: shot, fullPage: true });
      metrics.screenshots.push(shot);
      if (label === 'desktop') {
        const probes = await page.evaluate(async () => {
          const results = [];
          for (const target of ['/api/analyze', '/api/composition/preview']) {
            try {
              const response = await fetch(target, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
              });
              results.push({ target, reached: true, status: response.status });
            } catch (error) {
              results.push({ target, reached: false, error: String(error) });
            }
          }
          return results;
        });
        metrics.post_probes = probes;
        metrics.actual_analysis_posts = probes.filter(item => item.reached).length;
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }
  metrics.finished_at = new Date().toISOString();
  metrics.contains_scripts = metrics.viewports.some(item => item.scripts > 0);
  metrics.no_horizontal_overflow = metrics.viewports.every(item => item.scrollWidth <= item.innerWidth);
  metrics.ok = metrics.actual_analysis_posts === 0
    && metrics.blocked_posts.length === 2
    && metrics.blocked_external_requests.length === 0
    && metrics.page_errors.length === 0
    && metrics.contains_scripts === false
    && metrics.no_horizontal_overflow === true;
  fs.writeFileSync(path.join(out, 'replay-metrics.json'), JSON.stringify(metrics, null, 2));
  if (!metrics.ok) {
    console.error(JSON.stringify(metrics, null, 2));
    process.exitCode = 1;
  } else {
    console.log(JSON.stringify({
      ok: metrics.ok, blocked_posts: metrics.blocked_posts.length,
      actual_analysis_posts: metrics.actual_analysis_posts,
      external: metrics.blocked_external_requests.length,
      screenshots: metrics.screenshots,
    }));
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
