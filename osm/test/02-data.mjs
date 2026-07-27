// Where the map comes from and how long it is kept: the OSM API in tiles, an
// index rather than whole objects, tags read by id for what is on screen, and a
// device location that is only ever read on a press.
//
// The load-bearing claims here are the ones that would cost a mapper real time
// or real trust if they broke: a second photo in the same place must need no
// network, the store must not grow without bound, staged edits must survive
// eviction, and the page must never reach for a position it was not offered.
import { launch, open, reporter, setMode, photo, pickPhoto, findNearby, selectFirst,
         settled, goReady } from './lib.mjs';
import { devices } from 'playwright';

const { check, done } = reporter('data');
const browser = await launch();
await setMode();

const store = page => page.evaluate(() => {
  const pick = p => Object.keys(localStorage).filter(k => k.startsWith(p));
  return {
    tiles: pick('photomap:tile:'), els: pick('photomap:el:'),
    bytes: [...pick('photomap:tile:'), ...pick('photomap:el:')]
      .reduce((n, k) => n + localStorage.getItem(k).length, 0),
  };
});

// ---- cold: one bbox call, an index on disk, tags by id ---------------------
let saved;
{
  const { ctx, page, errors, calls } = await open(browser);
  await pickPhoto(page);
  await findNearby(page);
  await page.waitForTimeout(1200);          // let the by-id tag reads land

  const map = calls.filter(u => /\/map\.json/.test(u));
  const byId = calls.filter(u => /\/(node|way|relation)s\.json/.test(u));
  check('one bbox call to the OSM API answers the search',
    map.length === 1 && /bbox=/.test(map[0]), `${map.length}: ${map[0]?.slice(0, 46)}`);
  check('Overpass is not touched on the happy path', !calls.some(u => /overpass/.test(u)));
  check('tags are read by id, batched by type, only for what is listed',
    byId.length >= 1 && byId.length <= 3, byId.map(u => u.slice(0, 34)).join(' '));

  // An index, not objects. Full tags for one central-London tile would be
  // 800 kB against a roughly 5 MB budget; six fields a row is 8 kB.
  const shape = await page.evaluate(() => {
    const k = Object.keys(localStorage).find(x => x.startsWith('photomap:tile:'));
    const v = JSON.parse(localStorage.getItem(k));
    return { widths: [...new Set(v.rows.map(r => r.length))], row: v.rows[0], n: v.rows.length };
  });
  check('what is stored is an index, not the objects',
    shape.widths.length === 1 && shape.widths[0] === 6 && shape.row.every(v => typeof v !== 'object'),
    JSON.stringify(shape.row));
  const s = await store(page);
  check('the whole area is held, not just the ten shown', shape.n > 10, `${shape.n} rows`);
  check('and it costs kilobytes, not megabytes', s.bytes < 250_000, `${Math.round(s.bytes / 1024)} kB`);

  await selectFirst(page);
  await page.waitForTimeout(600);
  const detail = await page.textContent('#featureDetail');
  check('selecting one shows its full tags',
    /Coordinates/.test(detail) && !/Reading its tags/.test(detail));
  check('no uncaught JS errors reading the map', errors.length === 0, JSON.stringify(errors.slice(0, 2)));

  saved = await page.evaluate(() => JSON.stringify(Object.fromEntries(
    Object.keys(localStorage).filter(k => /^photomap:(tile|el):/.test(k))
      .map(k => [k, localStorage.getItem(k)]))));
  await ctx.close();
}

// ---- warm: the same place, with the network cut ----------------------------
{
  const { ctx, page, errors, calls } = await open(browser, { seed: saved });
  await ctx.setOffline(true);
  calls.length = 0;
  const t0 = Date.now();
  await pickPhoto(page);
  await findNearby(page);
  const ms = Date.now() - t0;
  const rows = await page.evaluate(() => document.querySelectorAll('#nearbyList .list-group-item').length);

  check('a photo in an area already held answers with the network off', rows === 10, `${rows} rows`);
  check('and asks nobody anything', calls.length === 0, calls.join(' '));
  check('and is quick about it', ms < 6000, `${ms} ms`);
  check('the line says the answer came from this browser',
    /held in this browser/.test(await page.textContent('#nearbySource')));
  await selectFirst(page);
  await page.waitForTimeout(400);
  check('and selection still shows tags, from the element cache',
    !/Reading its tags/.test(await page.textContent('#featureDetail')));
  check('no uncaught JS errors offline', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.setOffline(false);
  await ctx.close();
}

// ---- the store is bounded, and eviction is surgical ------------------------
{
  const { ctx, page } = await open(browser);
  await page.evaluate(() => {
    localStorage.setItem('photomap:changes:1:node/1', JSON.stringify({ osm: 'node/1', tags: { a: 'b' } }));
    localStorage.setItem('photomap:osm:1:dev', JSON.stringify({ access_token: 'keep-me' }));
    for (let i = 0; i < 60; i++) {
      localStorage.setItem(`photomap:tile:1:14/${i}/1`,
        JSON.stringify({ rows: [], fetchedAt: Date.now() - (60 - i) * 1000 }));
    }
  });
  await pickPhoto(page);
  await findNearby(page);
  const after = await page.evaluate(() => ({
    tiles: Object.keys(localStorage).filter(k => k.startsWith('photomap:tile:')).length,
    changes: !!localStorage.getItem('photomap:changes:1:node/1'),
    token: !!localStorage.getItem('photomap:osm:1:dev'),
  }));
  check('the tile store is capped', after.tiles <= 24, `${after.tiles} tiles`);
  // A quota error used to wipe every photomap: key, unsent work included.
  check('eviction never touches staged edits', after.changes);
  check('eviction never touches the OSM token', after.token);
  await ctx.close();
}

// ---- forgetting it, from Settings ------------------------------------------
{
  const { ctx, page, errors, calls } = await open(browser);
  await pickPhoto(page);
  await findNearby(page);
  await page.evaluate(() => {
    localStorage.setItem('photomap:changes:1:node/1', JSON.stringify({ osm: 'node/1', tags: { a: 'b' } }));
  });
  await page.click('#btnSettings');
  await page.waitForSelector('#settingsModal.show', { timeout: 10000 });
  await page.waitForTimeout(300);
  check('Settings reports what is held',
    /\d+ areas? and \d+ objects? held, \d+ kB/.test(await page.textContent('#mapCacheNote')),
    (await page.textContent('#mapCacheNote')).trim());
  // It is reached mid-survey, after adding something in another editor, so it
  // must not sit below two long sections.
  check('and the control is near the top of the dialog',
    (await page.evaluate(() => [...document.querySelectorAll('#settingsModal h3')]
      .map(h => h.textContent.trim())))[1] === 'Cached map');

  calls.length = 0;
  const pressedAt = await page.evaluate(() => Date.now());
  await page.click('#btnForgetMap');
  await page.waitForTimeout(400);
  const after = await page.evaluate(t => ({
    // Not "nothing is held": pressing this re-runs the search on purpose, so
    // some of it is already back. What must be gone is the old copy.
    stale: Object.keys(localStorage).filter(k => /^photomap:(tile|el):/.test(k))
      .filter(k => (JSON.parse(localStorage.getItem(k)).fetchedAt || 0) < t).length,
    changes: !!localStorage.getItem('photomap:changes:1:node/1'),
    note: document.getElementById('mapCacheNote').textContent.trim(),
  }), pressedAt);
  check('pressing it drops every held area and object', after.stale === 0, `${after.stale} stale`);
  check('it takes effect at once, not on Save', /Forgotten/.test(after.note), after.note);
  check('and it leaves staged edits alone', after.changes);
  // The reason for pressing it is "show me the thing I just added elsewhere",
  // so leaving the reader to find their own way back would answer half of it.
  await page.waitForFunction(() =>
    document.querySelectorAll('#nearbyList .list-group-item').length > 0, null, { timeout: 60000 });
  check('the search re-runs by itself', calls.some(u => /\/map\.json/.test(u)));
  check('no uncaught JS errors forgetting the map', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- the device location, only on a press ----------------------------------
{
  const ctx = await browser.newContext({
    ...devices['iPhone 17'],
    permissions: ['geolocation'],                    // granted, and still not read
    geolocation: { latitude: 53.9896, longitude: -1.5515, accuracy: 12 },
  });
  const page = await ctx.newPage();
  let reads = 0;
  await page.exposeFunction('__geoRead', () => { reads++; });
  await page.addInitScript(() => {
    const g = navigator.geolocation;
    const o = { get: g.getCurrentPosition, watch: g.watchPosition };
    g.getCurrentPosition = (...a) => { window.__geoRead?.(); return o.get.apply(g, a); };
    g.watchPosition = (...a) => { window.__geoRead?.(); return o.watch.apply(g, a); };
  });
  await goReady(page);
  await page.waitForTimeout(2500);
  check('loading the page reads no location', reads === 0, `${reads} reads`);

  // A photo taken moments ago with no GPS of its own used to adopt the fix by
  // itself. "Where the phone is now" is a guess about where a photo was taken.
  await page.setInputFiles('#fileInput', photo('justnow.jpg'));
  await page.waitForSelector('#phaseGps.show', { timeout: 30000 });
  await page.waitForTimeout(600);
  check('a just-taken photo with no GPS is not placed for you',
    reads === 0 && /No location yet/.test(await page.textContent('#phaseGpsSummary')));
  check('step 3 stays locked until it has a position',
    await page.locator('#phaseNearbyBtn[disabled]').count() === 1);

  await page.click('#btnUseFix');
  await page.waitForFunction(() =>
    !/No location yet/.test(document.getElementById('phaseGpsSummary').textContent),
    null, { timeout: 30000 });
  check('pressing the button reads it, once', reads === 1, `${reads} reads`);
  check('and the pane says the position is the device\'s',
    /From your device/.test(await page.textContent('#gpsSource')));

  // The first good fix is kept; holding the GPS open past it spends battery on
  // a question nobody asked again.
  await page.click('#phasePhotoBtn'); await settled(page);
  await page.click('#btnReplace'); await page.waitForTimeout(400);
  await page.setInputFiles('#fileInput', photo('nogps.jpg'));
  await page.waitForSelector('#phaseGps.show', { timeout: 30000 });
  await page.click('#btnUseFix');
  await page.waitForFunction(() =>
    !/No location yet/.test(document.getElementById('phaseGpsSummary').textContent),
    null, { timeout: 30000 });
  check('a second photo reuses that fix rather than re-reading', reads === 1, `${reads} reads`);
  await ctx.close();
}

// ---- a refusal is recoverable ----------------------------------------------
{
  const ctx = await browser.newContext({ ...devices['iPhone 17'] });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = (ok, err) =>
      setTimeout(() => err({ code: 1, PERMISSION_DENIED: 1, message: 'User denied Geolocation' }), 150);
  });
  await goReady(page);
  await page.setInputFiles('#fileInput', photo('nogps.jpg'));
  await page.waitForSelector('#phaseGps.show', { timeout: 30000 });
  await page.click('#btnUseFix');
  await page.waitForTimeout(600);
  check('a refused location says so and can be tried again',
    /Location is turned off for this page/.test(await page.textContent('#gpsBody'))
    && /Try my location again/.test(await page.textContent('#btnUseFix')));
  check('and the other way out is still there',
    await page.locator('#btnRetakeGps').count() === 1);
  await ctx.close();
}

// ---- the API refusing an area falls back to Overpass -----------------------
{
  await setMode({ osmMapFail: true });
  const { ctx, page, errors, calls } = await open(browser);
  await pickPhoto(page);
  await findNearby(page);
  const rows = await page.evaluate(() => document.querySelectorAll('#nearbyList .list-group-item').length);
  const source = (await page.textContent('#nearbySource')).replace(/\s+/g, ' ').trim();
  check('a refused bbox does not end the search', rows > 0, `${rows} rows`);
  check('it falls back to Overpass, and says so',
    calls.some(u => /overpass/.test(u)) && /would not serve/.test(source), source);
  check('and nothing is cached from a fallback', (await store(page)).tiles.length === 0);
  check('no uncaught JS errors on the fallback path', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
  await setMode();
}

await browser.close();
done();
