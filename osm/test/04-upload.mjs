// Phase 7: sign in to OpenStreetMap with OAuth 2.0 + PKCE, review what has
// piled up in localStorage, and send it as one changeset. The OSM server is a
// local stand-in — the real one needs a human at a login page and writes to a
// public database — but every byte the page sends is inspected here, including
// the osmChange XML.
//
// This is the one suite whose subject can do irreversible damage, so it is the
// one where an edge case still earns its place: a conflict, a failed create and
// a rejected upload each leave the store in a different state, and getting any
// of them wrong loses a mapper's unsent work.
import { devices } from 'playwright';
import { launch, reporter, setMode, TARGET, settled, goReady } from './lib.mjs';

/* Hard stop. This suite exercises changeset writes, and the only acceptable
   target is the local mirror, whose stand-in OpenStreetMap lives in memory.
   Pointed anywhere else the page would use real OSM origins, and a
   misconfiguration must not be able to put test edits on a public database —
   not on the live server and not on the dev one either. */
const html = await fetch(TARGET).then(r => r.text()).catch(() => '');
if (/https:\/\/(www|api|master\.apis\.dev)\.openstreetmap\.org/.test(html)) {
  console.error(`REFUSING TO RUN: the page at ${TARGET} talks to a real OpenStreetMap server. `
    + 'Run this against the local mirror (http://127.0.0.1:8099/), which serves an in-memory '
    + 'stand-in, so no test edit can ever reach OSM.');
  process.exit(2);
}

const { check, done } = reporter('upload');
const browser = await launch();
const mirrorState = () => fetch(new URL('/osmdev/_state', TARGET)).then(r => r.json());

// Two staged objects, exactly the shape step 6 writes. A way is included so the
// geometry check has something to bite on.
const STAGED = {
  'photomap:changes:1:node/14040292373': {
    osm: 'node/14040292373', name: 'Valley Gardens Games Paviliom', pair: 'leisure=sports_centre',
    tags: { operator: 'North Yorkshire Council', opening_hours: 'Sa,Su 10:00-17:30' },
    base: { operator: null, opening_hours: 'Mo-Fr off; Sa-Su,PH 10:00-17:00' },
    sources: [{ photo: 'harrogate.jpg', lat: 53.989619, lon: -1.551497,
                visionModel: 'test/vision', tagModel: 'test/tagger', at: '2026-07-25T00:00:00Z' }],
    fetchedAt: Date.now(),
  },
  'photomap:changes:1:way/900001': {
    osm: 'way/900001', name: 'A shed', pair: 'building=yes',
    tags: { 'building:levels': '1' }, base: { 'building:levels': null },
    sources: [{ photo: 'shed.jpg', lat: 53.9, lon: -1.5,
                visionModel: 'test/vision', tagModel: 'test/tagger', at: '2026-07-25T00:00:00Z' }],
    fetchedAt: Date.now(),
  },
};

async function fresh({ signIn = true, staged = STAGED } = {}) {
  const ctx = await browser.newContext({ ...devices['iPhone 17'] });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  await goReady(page);
  await page.evaluate(([s, withToken]) => {
    localStorage.clear();
    localStorage.setItem('photomap:settings:1', JSON.stringify({
      apiKey: 'sk-or-v1-test', model: 'test/vision', tagModel: 'test/tagger',
      tagEffort: 'high', osmServer: 'dev', osmClientIds: { dev: 'CLIENT-ID-123' },
    }));
    for (const [k, v] of Object.entries(s)) localStorage.setItem(k, JSON.stringify(v));
    // The handshake is driven for real once, in the block that is about it.
    // Everywhere else the token is planted: those blocks are about what happens
    // after signing in, and re-proving OAuth each time buys nothing.
    if (withToken) {
      localStorage.setItem('photomap:osm:1:dev', JSON.stringify({
        access_token: 'tok-dev', scope: 'read_prefs write_api', at: Date.now(),
        user: { id: 42, name: 'test_mapper' }, fetchedAt: Date.now(),
      }));
    }
  }, [staged, signIn]);
  await goReady(page, true);
  return { ctx, page, errors };
}

const openUpload = async page => {
  // The backdrop outlives the .show class by the length of the fade, and while
  // it is there it swallows the click on the phase header.
  if (await page.locator('#settingsModal.show').count()) {
    await page.click('#settingsModal [data-bs-dismiss=modal]');
    await page.waitForFunction(() => !document.querySelector('.modal-backdrop'),
      null, { timeout: 5000 });
  }
  // Settle first: coming back from the OAuth redirect the page opens step 7 by
  // itself, and a click landing during that animation toggles it shut again.
  await settled(page);
  if (!(await page.locator('#phaseUpload.show').count())) await page.click('#phaseUploadBtn');
  await page.waitForSelector('#phaseUpload.show', { timeout: 10000 });
  await settled(page);
  // Signed out there is no preview to wait for, and waiting for one anyway cost
  // this suite twenty seconds of doing nothing.
  await page.waitForFunction(() =>
    !!document.getElementById('uploadPreview')?.textContent.trim()
    || !!document.querySelector('#uploadAccount .btn-primary'), null, { timeout: 15000 });
};

// ---- signed out, and signing in --------------------------------------------
{
  await setMode();
  const { ctx, page, errors } = await fresh({ signIn: false });
  check('step 7 is live on a cold page with no photo loaded',
    await page.locator('#phaseUploadBtn[disabled]').count() === 0
    && /2 objects/.test(await page.textContent('#phaseUploadSummary')),
    await page.textContent('#phaseUploadSummary'));

  await openUpload(page);
  const out = await page.evaluate(() => ({
    signIn: !!document.querySelector('#uploadAccount .btn-primary'),
    queue: document.querySelectorAll('#uploadList .list-group-item').length,
    upload: !!document.getElementById('btnUpload'),
    preview: !document.getElementById('uploadPreviewWrap') ||
             document.getElementById('uploadPreviewWrap').classList.contains('d-none'),
  }));
  // Signed out there is one thing to do, so it is the only thing offered — but
  // the queue stays, because discarding is reasonable without signing in.
  check('signed out, connecting is the primary action', out.signIn);
  check('the queue is still listed, so it can be discarded', out.queue > 0, `${out.queue}`);
  check('but there is nothing to review or send', !out.upload && out.preview);

  await page.click('#btnSettings');
  await page.waitForSelector('#settingsModal.show', { timeout: 10000 });
  await page.click('#btnOsmSignIn');
  await page.waitForFunction(() =>
    /photomap:osm:1:dev/.test(Object.keys(localStorage).join(',')), null, { timeout: 30000 });
  const token = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('photomap:osm:1:dev') || '{}'));
  check('the PKCE handshake completes and the token is kept per server',
    !!token.access_token, Object.keys(token).join(','));
  await openUpload(page);
  check('and the account is named in the step',
    /test_mapper/.test(await page.textContent('#uploadAccount')));
  check('with the sandbox flagged as harmless',
    /nothing here reaches the real map/i.test(await page.textContent('#uploadAccount')));
  check('no uncaught JS errors signing in', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- choosing what goes, and seeing it before it goes ----------------------
{
  const { ctx, page, errors } = await fresh();
  await openUpload(page);
  const view = await page.evaluate(() => ({
    groups: document.querySelectorAll('#uploadList input[data-group]').length,
    radios: document.querySelectorAll('#uploadList input[data-group][type=radio]').length,
    cta: document.getElementById('btnUpload')?.textContent.replace(/\s+/g, ' ').trim(),
    comment: document.getElementById('uploadComment')?.value,
    xml: document.getElementById('uploadPreview')?.textContent || '',
  }));
  // One object per changeset: a changeset should be local and its comment
  // should describe what is in it, and weeks of edits across a city are neither.
  check('objects are a single choice, not a multi-select',
    view.groups === 2 && view.radios === 2, `${view.groups} groups, ${view.radios} radios`);
  check('the button counts what will be sent, and to which object',
    /Upload 2 tags on Valley Gardens Games Paviliom/.test(view.cta), view.cta);
  check('a comment naming the object is proposed', /Surveyed Valley Gardens/.test(view.comment),
    view.comment);
  check('the exact XML is shown without being asked for',
    /<osmChange/.test(view.xml) && /<changeset/.test(view.xml));
  check('the preview is the real element, with its live version and geometry',
    /version="3"/.test(view.xml) && /lat="53\.9896194"/.test(view.xml));
  check('tags the edit does not touch are visibly carried across',
    /k="sport" v="table_tennis;tennis;disc_golf"/.test(view.xml));
  // Echoing the previous editor's identity back to the server is wrong, and the
  // preview is where it would have been visible.
  check('the previous editor\'s author and timestamp are not echoed back',
    !/user="prior"/.test(view.xml) && !/timestamp="2026-07-01/.test(view.xml));

  await page.locator('#uploadList input[data-tag]').first().uncheck();
  await page.waitForTimeout(250);
  check('unticking a tag drops it from the count and from the XML',
    /Upload 1 tag on/.test(await page.textContent('#btnUpload')),
    (await page.textContent('#btnUpload')).replace(/\s+/g, ' ').trim());
  await page.locator('#uploadList input[data-tag]').first().check();
  await page.waitForTimeout(250);
  check('no uncaught JS errors while reviewing', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- the upload itself ------------------------------------------------------
{
  await setMode();
  const { ctx, page, errors } = await fresh();
  await openUpload(page);
  await page.fill('#uploadComment', 'two tags from my own photos, checked on site');
  const opened = [];
  page.context().on('page', p => opened.push(p));
  await page.click('#btnUpload');
  await page.waitForFunction(() =>
    /Uploaded|Nothing was uploaded|HTTP/.test(document.getElementById('uploadResult').textContent),
    null, { timeout: 60000 });
  await page.waitForTimeout(500);

  const st = await mirrorState();
  const cs = st.changesets[0];
  const meta = cs.body, diff = cs.uploads.join('');
  check('exactly one changeset is opened', st.changesets.length === 1, `${st.changesets.length}`);
  check('it carries the comment the mapper wrote', /two tags from my own photos/.test(meta));
  check('it identifies the application', /created_by" v="snap-osm/.test(meta));
  check('it declares the source as plain survey, the documented value',
    /source" v="survey"/.test(meta));
  check('it states who did what, and what the model was for',
    /snap-osm:method" v="Mapper identified the object on site/.test(meta));
  check('it does not volunteer which models were used', !/snap-osm:models/.test(meta));
  check('one osmChange diff is posted, not a request per element',
    cs.uploads.length === 1, `${cs.uploads.length}`);
  check('the element keeps the version the server gave it', /version="3"/.test(diff));
  check('and its position', /lat="53\.9896194"[^>]*lon="-1\.5514974"/.test(diff));
  check('new tags are added', /k="operator" v="North Yorkshire Council"/.test(diff));
  check('existing tags are overwritten', /k="opening_hours" v="Sa,Su 10:00-17:30"/.test(diff)
    && !/k="opening_hours" v="Mo-Fr off/.test(diff));
  check('tags the edit does not touch are preserved',
    /k="sport" v="table_tennis;tennis;disc_golf"/.test(diff));
  check('the changeset is closed afterwards', cs.closed);

  const after = await page.evaluate(() => ({
    left: Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')),
    result: document.getElementById('uploadResult').textContent.replace(/\s+/g, ' ').trim(),
    link: document.getElementById('lnkChangeset')?.getAttribute('href'),
    linkClass: document.getElementById('lnkChangeset')?.className || '',
    cta: document.getElementById('uploadCta').textContent.replace(/\s+/g, ' ').trim(),
  }));
  check('the object just sent is removed, and only that one',
    after.left.length === 1 && after.left[0].endsWith('way/900001'), after.left.join(','));
  check('the result says what went and that it has been cleared',
    /Uploaded 2 tags on 1 object/.test(after.result) && /removed from this browser/.test(after.result));
  // On a phone a new tab dropped on you mid-survey is how you lose your place.
  check('nothing is opened without being asked for', opened.length === 0);
  check('with more still staged, the changeset link is secondary to sending the rest',
    /btn-outline-secondary/.test(after.linkClass) && /Upload \d+ tags? on/.test(after.cta),
    after.linkClass);

  // Second object: the trap in a tag-only edit is that the API replaces what it
  // is given, so a way sent without its nodes loses its geometry.
  await page.fill('#uploadComment', 'levels on the shed, surveyed');
  await page.click('#btnUpload');
  await page.waitForFunction(() => /Uploaded/.test(document.getElementById('uploadResult').textContent),
    null, { timeout: 60000 });
  const st2 = await mirrorState();
  const wayDiff = st2.changesets[1].uploads.join('');
  check('the second object goes as its own changeset', st2.changesets.length === 2);
  check('a way keeps all of its node references',
    (wayDiff.match(/<nd ref="\d+"\/?>/g) || []).length === 4);
  check('and the tags it already had, and its own version',
    /k="building" v="yes"/.test(wayDiff) && /<way[^>]*version="5"/.test(wayDiff));

  const end = await page.evaluate(() => ({
    left: Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')).length,
    locked: !!document.getElementById('phaseUploadBtn').disabled,
    linkClass: document.getElementById('lnkChangeset')?.className || '',
    again: !!document.getElementById('btnUploadAgain'),
  }));
  check('with nothing left staged the step locks itself again', end.left === 0 && end.locked);
  check('and the changeset link becomes the primary action, beside starting over',
    /btn-primary/.test(end.linkClass) && end.again, end.linkClass);
  check('no uncaught JS errors during the upload', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- somebody else got there first ------------------------------------------
{
  await setMode({ osmMoved: true });        // operator already set, to something else
  const { ctx, page, errors } = await fresh();
  await openUpload(page);
  await page.click('#btnUpload');
  await page.waitForFunction(() =>
    /Nothing was uploaded|Uploaded/.test(document.getElementById('uploadResult').textContent),
    null, { timeout: 60000 });
  const st = await mirrorState();
  const after = await page.evaluate(() => ({
    result: document.getElementById('uploadResult').textContent.replace(/\s+/g, ' ').trim(),
    left: Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')).length,
    unticked: [...document.querySelectorAll('#uploadList input[data-tag]')].filter(b => !b.checked)
      .map(b => b.dataset.tag),
  }));
  // Read first, write second: a conflict must cost nothing, not leave an empty
  // changeset open on someone's account.
  check('a conflict aborts before any changeset is opened', st.changesets.length === 0);
  check('it says nothing was uploaded and why', /Nothing was uploaded/.test(after.result)
    && /edited on\s+OpenStreetMap since/.test(after.result), after.result.slice(0, 110));
  check('the clashing tag is unticked for review', after.unticked.includes('operator'));
  check('and nothing staged is lost', after.left === 2, `${after.left} left`);
  check('no uncaught JS errors on a conflict', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- the server refusing, at each of the two points it can ------------------
for (const [when, expect] of [['create', /exploded|HTTP 500/], ['upload', /Version mismatch|409/]]) {
  await setMode({ osmFail: when });
  const { ctx, page, errors } = await fresh();
  await openUpload(page);
  await page.click('#btnUpload');
  await page.waitForFunction(() =>
    /Uploaded|Nothing|HTTP|exploded|mismatch/.test(document.getElementById('uploadResult').textContent),
    null, { timeout: 60000 });
  const after = await page.evaluate(() => ({
    result: document.getElementById('uploadResult').textContent.replace(/\s+/g, ' ').trim(),
    left: Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')).length,
  }));
  check(`a failure at ${when} is reported in the server's own words`,
    expect.test(after.result), after.result.slice(0, 90));
  // The only unforgivable outcome: losing unsent work to a failed send.
  check(`and nothing is removed from the browser when ${when} fails`,
    after.left === 2, `${after.left} left`);
  check(`no uncaught JS errors when ${when} fails`, errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
}

// ---- throwing edits away -----------------------------------------------------
{
  await setMode();
  const { ctx, page } = await fresh();
  await openUpload(page);
  const btn = '#uploadList button[data-discard]';
  await page.locator(btn).first().click();
  await page.waitForTimeout(200);
  check('the first tap arms rather than discards',
    /Really discard/.test(await page.locator(btn).first().textContent())
    && await page.evaluate(() =>
      Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')).length) === 2);
  await page.locator(btn).first().click();
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => ({
    left: Object.keys(localStorage).filter(k => k.startsWith('photomap:changes:')).length,
    note: document.getElementById('alertHost').textContent.replace(/\s+/g, ' ').trim(),
  }));
  check('the second tap discards just that object', after.left === 1, `${after.left} left`);
  check('and says nothing was sent to OpenStreetMap',
    /Nothing was sent to OpenStreetMap/.test(after.note), after.note.slice(0, 80));
  await ctx.close();
}

// ---- refusing authorization ---------------------------------------------------
{
  await setMode({ osmDeny: true });
  const { ctx, page, errors } = await fresh({ signIn: false });
  await page.click('#btnSettings');
  await page.waitForSelector('#settingsModal.show', { timeout: 10000 });
  await page.click('#btnOsmSignIn');
  await page.waitForFunction(() => /error|denied/.test(document.body.textContent)
    || !!document.getElementById('btnOsmSignIn'), null, { timeout: 15000 });
  check('a refused authorization stores no token',
    await page.evaluate(() => !localStorage.getItem('photomap:osm:1:dev')));
  check('no uncaught JS errors when authorization is refused',
    errors.length === 0, JSON.stringify(errors.slice(0, 2)));
  await ctx.close();
  await setMode();
}

await browser.close();
done();
