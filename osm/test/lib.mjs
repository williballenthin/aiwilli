// Shared harness. The expensive thing in these suites is driving the page from
// a photo to a set of proposals — five phases, three of them network-bound — so
// everything here exists to do that once per file and then vary what happens
// afterwards, rather than starting over for each scenario.
//
// Two things make that possible:
//   - the mirror records every upstream response to disk and replays it, so the
//     same drive costs the same every time instead of anywhere from 11 to 39
//     seconds depending on how busy taginfo is;
//   - scenarios are chosen by POSTing to the mirror's /_mode instead of
//     restarting it, so switching costs milliseconds and suites could be run in
//     parallel.
import { chromium, devices } from 'playwright';

// Not named URL: that would shadow the global constructor used just below.
export const TARGET = process.env.TARGET || 'http://127.0.0.1:8099/';
export const FIXTURES = new URL('./fixtures/', import.meta.url).pathname;
export const photo = name => FIXTURES + name;

/** A pass/fail recorder. One per suite; `done()` exits the process. */
export function reporter(title) {
  let failed = 0, total = 0;
  const t0 = Date.now();
  console.log(`\n### ${title}`);
  return {
    check(name, ok, extra = '') {
      total++;
      if (!ok) failed++;
      console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
    },
    done() {
      const secs = ((Date.now() - t0) / 1000).toFixed(1);
      console.log(`\n${failed === 0 ? 'ALL CHECKS PASSED' : failed + ' CHECK(S) FAILED'}`
        + `  (${total} checks, ${secs}s)`);
      process.exit(failed === 0 ? 0 : 1);
    },
  };
}

export const launch = () => chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  proxy: { server: process.env.HTTPS_PROXY || 'http://127.0.0.1:44329', bypass: 'localhost,127.0.0.1,::1' },
});

/** Pick the scenario the mirror plays. No argument resets it to the defaults. */
export const setMode = async (mode = {}) =>
  (await fetch(new URL('/_mode', TARGET), { method: 'POST', body: JSON.stringify(mode) })).json();

const SETTINGS = {
  apiKey: 'sk-or-v1-test', model: 'google/gemini-3.6-flash',
  tagModel: 'anthropic/claude-opus-5', tagEffort: 'high',
};

/**
 * A page with an empty store and a working configuration, recording script
 * faults. A failed subresource is not one: several suites cut the network or
 * make the mirror refuse a request on purpose.
 */
export async function open(browser, { device = 'iPhone 17', settings = SETTINGS, seed = null,
                                      ...ctxOpts } = {}) {
  const ctx = await browser.newContext({ ...devices[device], ...ctxOpts });
  const page = await ctx.newPage();
  const errors = [], calls = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) {
      errors.push('console: ' + m.text());
    }
  });
  page.on('request', r => {
    const u = r.url();
    if (/\/api\/0\.6\/|\/overpass\/|key\/values/.test(u)) calls.push(u.replace(/^https?:\/\/[^/]+/, ''));
  });
  await goReady(page);
  await page.evaluate(([s, seeded]) => {
    localStorage.clear();
    for (const [k, v] of Object.entries(JSON.parse(seeded || '{}'))) localStorage.setItem(k, v);
    if (s) localStorage.setItem('photomap:settings:1', s);
  }, [settings ? JSON.stringify(settings) : null, seed]);
  await goReady(page, true);
  return { ctx, page, errors, calls };
}

/**
 * Load the page and wait for its script to finish, which it signals by filling
 * in the dropzone hint as its last act. `networkidle` waits half a second of
 * silence on top of that, and across the thirty-odd navigations these suites
 * make it was costing more than every assertion put together.
 */
export async function goReady(page, reload = false) {
  if (reload) await page.reload({ waitUntil: 'domcontentloaded' });
  else await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForFunction(() =>
    !!document.getElementById('dropzoneHint')?.textContent, null, { timeout: 30000 });
}

/* ---- the drive, in the pieces a suite might want to stop between ---- */

export async function pickPhoto(page, file = 'harrogate.jpg') {
  await page.setInputFiles('#fileInput', photo(file));
  await page.waitForSelector('#phaseGps.show', { timeout: 30000 });
}

export async function findNearby(page) {
  await page.click('#btnGoNearby');
  await page.waitForFunction(() =>
    document.querySelectorAll('#nearbyList .list-group-item').length > 0
    || document.querySelector('#nearbyStatus .alert-warning'), null, { timeout: 60000 });
}

export const selectFirst = async page => {
  await page.click('#nearbyList .list-group-item:nth-child(1)');
  await page.waitForFunction(() => !!document.getElementById('btnCtaUse'), null, { timeout: 10000 });
};

/**
  * Bootstrap's collapse takes 350 ms, during which two phases are both visible
  * and both their buttons answer to offsetParent. Anything asserting on what is
  * on screen has to wait this out or it sees a state the reader never does.
  */
export const settled = page =>
  page.waitForFunction(() => !document.querySelector('.collapsing'), null, { timeout: 10000 });

/** Commit the selection and wait for the schema, which unlocks steps 4 and 5. */
export async function commit(page) {
  await page.click('#btnCtaUse');
  await page.waitForFunction(() =>
    document.getElementById('phaseSchemaNum').classList.contains('is-done')
    || !!document.getElementById('btnRetrySchema'), null, { timeout: 60000 });
  await page.waitForSelector('#btnRunVision', { timeout: 20000 });
  await settled(page);
}

export async function describe(page) {
  await page.click('#btnRunVision');
  await page.waitForFunction(() =>
    document.getElementById('phaseVisionNum').classList.contains('is-done'), null, { timeout: 60000 });
}

export async function openPropose(page) {
  await page.click('#btnCtaPropose');
  await page.waitForFunction(() =>
    document.getElementById('propPromptText').textContent.length > 300, null, { timeout: 60000 });
  await settled(page);
}

/**
 * Run the tagging call and wait for every annotation to land. Cheap — about a
 * third of a second — which is what lets a suite try several model outputs
 * against one drive instead of starting over for each.
 */
export async function propose(page) {
  await page.click('#btnRunPropose');
  await settled(page);
  // The three annotation passes — the output filter, opening_hours and the
  // vocabulary lookups — are awaited before the list is drawn, and the phase is
  // only marked done after that, so this one wait covers all of it.
  await page.waitForFunction(() =>
    document.getElementById('phaseProposeNum').classList.contains('is-done'), null, { timeout: 60000 });
}

/** Photo to proposals, the whole way. */
export async function driveToProposals(page) {
  await pickPhoto(page);
  await findNearby(page);
  await selectFirst(page);
  await commit(page);
  await describe(page);
  await openPropose(page);
  await propose(page);
}

/* ---- reading the page ---- */

/** Every proposal row, as the reader sees it. */
export const proposalRows = page => page.evaluate(() =>
  [...document.querySelectorAll('#proposeList .list-group-item')].map(el => ({
    key: el.querySelector('code')?.textContent || '',
    value: el.querySelectorAll('code')[1]?.textContent || '',
    badges: [...el.querySelectorAll('.badge')].map(b => ({
      text: b.textContent.trim(), cls: b.className, title: b.getAttribute('title') || '',
    })),
    checked: !!el.querySelector('input')?.checked,
    selectable: !!el.querySelector('input'),
    text: el.textContent.replace(/\s+/g, ' ').trim(),
  })));

export const row = (rows, key, value) =>
  rows.find(r => r.key === key && (value === undefined || r.value === value));
export const badge = (r, re) => r?.badges.find(b => re.test(b.text));

/** Solid-primary buttons that are visible and pressable, by id and label. */
export const bluesOnScreen = page => page.evaluate(() =>
  [...document.querySelectorAll('.btn-primary')]
    .filter(e => e.offsetParent && !e.disabled)
    .map(e => `${e.id}: ${e.textContent.replace(/\s+/g, ' ').trim().slice(0, 34)}`));

/** Anything sticking out past the viewport, which on a phone means lost. */
export const overflows = page => page.evaluate(() => {
  const w = document.documentElement.clientWidth;
  // The document not scrolling sideways is the symptom that matters; the list
  // is only to name the culprit. Leaflet's own tile machinery is excluded
  // because it is positioned outside a clipped container by design.
  const wide = [...document.querySelectorAll('body *')]
    .filter(e => e.offsetParent && !e.closest('.leaflet-container')
                 && e.getBoundingClientRect().right > w + 1)
    .slice(0, 4).map(e => `${e.tagName}#${e.id || ''}.${e.className}`.slice(0, 60));
  if (document.documentElement.scrollWidth > w + 1) wide.unshift('document scrolls sideways');
  return wide;
});
