// Optional integration test: npm install playwright, install Chromium, then
// node tests/test_browser.cjs. PyScript's CDN must be reachable.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const root = path.resolve(__dirname, '..');
(async () => {
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROMIUM_PATH) launch.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(launch);
  const failures = [];
  for (const mobile of [false, true]) {
    const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1400, height: 1000 }, isMobile: mobile, hasTouch: mobile });
    page.on('pageerror', e => failures.push(`page error: ${e.message}`));
    await page.goto(pathToFileURL(path.join(root, 'index.html')).href);
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('Loaded'), null, {timeout: 60000});
    const sample = JSON.parse(fs.readFileSync(path.join(root, 'sample.json'), 'utf8'));
    for (const direction of ['TB', 'BT', 'LR', 'RL']) {
      sample.direction = direction;
      for (const expanded of [[], ['review'], ['execution'], ['review', 'decision', 'execution']]) {
        for (const zoom of [1, 1.25]) {
          await page.locator('#json-input').fill(JSON.stringify(sample));
          await page.locator('#render-button').click();
          for (const id of expanded) await page.locator(`[data-flow-toggle="${id}"]`).click();
          if (zoom > 1) await page.locator('#zoom-in').click();
          await page.waitForTimeout(60);
          const results = await page.evaluate(() => {
            const hits = (a,b) => a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
            return [...document.querySelectorAll('.flow-label')].flatMap(label => {
              const rect = label.getBoundingClientRect();
              const issues = [...document.querySelectorAll('.flow-node > .flow-head')].filter(n => hits(rect,n.getBoundingClientRect())).map(n => `${label.textContent} overlaps ${n.parentElement.dataset.nodeId}`);
              const edge = label.previousElementSibling, length = edge.getTotalLength(), matrix = edge.getScreenCTM(), steps = Math.max(1,Math.ceil(length / 2));
              let closest = Infinity;
              for (let i=0; i<=steps; i++) {
                const p=edge.getPointAtLength(length*i/steps).matrixTransform(matrix);
                const dx=Math.max(rect.left-p.x,0,p.x-rect.right),dy=Math.max(rect.top-p.y,0,p.y-rect.bottom);
                closest=Math.min(closest,Math.hypot(dx,dy));
              }
              if (closest > 8 * (rect.height / 17) + 1) issues.push(`${label.textContent} is ${closest.toFixed(1)}px from its line`);
              return issues;
            });
          });
          failures.push(...results.map(x => `${mobile?'mobile':'desktop'} ${direction} ${expanded.join(',')||'closed'} ${zoom}: ${x}`));
        }
      }
    }
    await page.close();
  }
  await browser.close();
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  console.log('All sample labels are clear of node headings and near their own paths.');
})().catch(e => { console.error(e); process.exit(1); });
