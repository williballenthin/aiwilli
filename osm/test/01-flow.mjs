// The path a mapper actually walks, once, with the things that would ruin it
// checked as we pass. Not an inventory of the interface — that is what the
// screenshots in TESTING.md are for — but the sequence has to hold: each step
// unlocks the next, the next thing to press is obvious, and nothing runs off
// the side of a phone.
import { launch, open, reporter, setMode, photo, pickPhoto, findNearby, selectFirst,
         commit, describe, openPropose, propose, bluesOnScreen, overflows, settled } from './lib.mjs';

const { check, done } = reporter('flow');
const browser = await launch();
await setMode();

const { page, errors } = await open(browser);

/* The one rule that keeps the flow legible: at any moment there is exactly one
   solid blue button — the next thing to press — or none, when the step is
   waiting on the reader to pick something. Everything else is outlined. This is
   checked at every stop rather than once, because it is the invariant that
   breaks silently as buttons are added. */
const onlyBlue = async (where, expected) => {
  const blue = await bluesOnScreen(page);
  check(`${where}: one primary action`, blue.length === (expected === null ? 0 : 1), blue.join(' | '));
  if (expected !== null) {
    check(`${where}: and it is "${expected}"`, blue[0]?.includes(expected), blue[0]);
  }
};

// ---- 1. the page, and its dependencies -------------------------------------
const shell = await page.evaluate(() => ({
  bootstrap: !!window.bootstrap, leaflet: !!window.L, exifr: !!window.exifr,
  styled: getComputedStyle(document.querySelector('.btn-primary') || document.body).backgroundColor,
  title: document.title,
  locked: ['Gps', 'Nearby', 'Schema', 'Vision', 'Propose']
    .filter(n => document.getElementById(`phase${n}Btn`).disabled),
  uploadLocked: document.getElementById('phaseUploadBtn').disabled,
  uploadVisible: !document.getElementById('phaseUpload')
    .closest('.accordion-item').classList.contains('d-none'),
}));
check('the libraries the page needs are loaded',
  shell.bootstrap && shell.leaflet && shell.exifr, JSON.stringify(shell));
check('every later phase starts locked', shell.locked.length === 5, shell.locked.join(','));
// Step 7 does not belong to this photo — it reads whatever has accumulated in
// localStorage — so it is on the page from the start, and locked only because
// nothing is staged yet.
check('step 7 is present from the start, locked only for want of anything staged',
  shell.uploadVisible && shell.uploadLocked);
check('nothing asks for a location before a button is pressed',
  await page.locator('#locStatus').count() === 0);
await onlyBlue('1. before a photo', null);

// ---- 2. the photo, and where it was taken ----------------------------------
await pickPhoto(page);
const gps = await page.evaluate(() => ({
  summary: document.getElementById('phaseGpsSummary').textContent,
  body: document.getElementById('gpsBody').textContent.replace(/\s+/g, ' '),
  photoDone: document.getElementById('phasePhotoNum').classList.contains('is-done'),
  mapShown: !document.getElementById('mapGps').classList.contains('d-none'),
}));
check('the EXIF position is read and shown', /53\.98962° N/.test(gps.summary), gps.summary);
check('and the photo is put on a map', gps.mapShown);
check('step 1 is marked done', gps.photoDone);
check('the position is credited to the photograph, not the device',
  /photograph’s own GPS/.test(gps.body), gps.body.slice(0, 60));
await onlyBlue('2. GPS', "Find what's nearby");

// ---- 3. what is mapped around it -------------------------------------------
await findNearby(page);
const near = await page.evaluate(() => ({
  rows: document.querySelectorAll('#nearbyList .list-group-item').length,
  pins: document.querySelectorAll('.leaflet-marker-icon .dot').length,
  radios: document.querySelectorAll('#nearbyList input[type=radio]').length,
  source: document.getElementById('nearbySource').textContent.replace(/\s+/g, ' ').trim(),
  first: document.querySelector('#nearbyList .list-group-item')?.textContent.replace(/\s+/g, ' ').trim(),
}));
check('the nearest things are listed', near.rows === 10, `${near.rows} rows`);
check('and each is on the map too', near.pins === near.rows, `${near.pins} pins`);
check('selection is a real radio, in the same column as every other list',
  near.radios === near.rows);
check('the map data is credited', /^via api\.openstreetmap\.org/.test(near.source), near.source);
check('the photographed object is among the results',
  /Valley Gardens Games Pavili/i.test(near.first || ''), near.first?.slice(0, 50));
await onlyBlue('3. nothing selected', null);

await selectFirst(page);
const picked = await page.evaluate(() => ({
  ticked: document.querySelectorAll('#nearbyList input:checked').length,
  tinted: document.querySelectorAll('#nearbyList .list-group-item-primary').length,
  solid: document.querySelectorAll('#nearbyList .list-group-item.active').length,
  detail: !document.getElementById('featureDetail').classList.contains('d-none'),
  auto: !!document.getElementById('btnCtaAuto'),
}));
check('picking one ticks exactly one radio', picked.ticked === 1);
check('and tints its row rather than filling it with the CTA blue',
  picked.tinted === 1 && picked.solid === 0);
check('the details of the pick are shown', picked.detail);
check('both routes on are offered side by side', picked.auto);
await onlyBlue('3. selected', 'Use ');
check('nothing runs off the side of the phone', (await overflows(page)).length === 0,
  (await overflows(page)).join(' | '));

// ---- 4 and 5. committing, the schema, the description ----------------------
await commit(page);
const afterCommit = await page.evaluate(() => ({
  header: document.getElementById('phaseNearbySummary').textContent,
  schemaDone: document.getElementById('phaseSchemaNum').classList.contains('is-done'),
  ticks: document.querySelectorAll('#schemaBody .bi-check2').length,
  circles: document.querySelectorAll('#schemaBody li .bi-circle, #schemaBody li .bi-check-circle-fill').length,
  visionOpen: document.getElementById('phaseVision').classList.contains('show'),
}));
check('the step header names what was committed', /^Using /.test(afterCommit.header), afterCommit.header);
check('the tag schema loads on commit', afterCommit.schemaDone);
check('fields the object already carries are ticked', afterCommit.ticks >= 1, `${afterCommit.ticks}`);
check('and the read-only marks cannot be mistaken for controls', afterCommit.circles === 0);
check('committing opens the description step', afterCommit.visionOpen);
await onlyBlue('5. arrived at describe', 'Describe this photo');

const prompt = await page.textContent('#visPromptText');
const committed = (await page.textContent('#phaseNearbySummary')).replace(/^Using /, '').trim();
check('the prompt names the committed entity and its position',
  prompt.includes(committed) && /53\.98962° N/.test(prompt), `committed=${committed}`);
check('and asks for text to be transcribed rather than summarised',
  /Transcribe every piece of legible text/.test(prompt));

await describe(page);
check('a description comes back', (await page.textContent('#visOutText')).length > 200);
await onlyBlue('5. described', 'Next: propose OSM tags');
check('and the run button steps aside once it has run',
  /btn-outline-primary/.test(await page.evaluate(() => document.getElementById('btnRunVision').className)),
  await page.evaluate(() => document.getElementById('btnRunVision').className));

// ---- 6. proposals ----------------------------------------------------------
await openPropose(page);
const propPrompt = await page.textContent('#propPromptText');
check('the tagging prompt carries the schema\'s own value lists',
  /ONE OF these values, and nothing else/.test(propPrompt));
check('and worked examples from real objects nearby',
  /idiomatic|examples/i.test(propPrompt), propPrompt.length + ' chars');
check('the mapper\'s note starts folded away',
  !(await page.evaluate(() => document.getElementById('proposeNoteWrap').open)));
await onlyBlue('6. arrived at propose', 'Propose tags');

await propose(page);
const staged = await page.evaluate(() => ({
  rows: document.querySelectorAll('#proposeList .list-group-item').length,
  groups: [...document.querySelectorAll('#proposeList h3')].map(h => h.textContent.replace(/\s+/g, ' ').trim()),
  cta: document.getElementById('btnSaveChangeset').textContent.trim(),
}));
check('proposals come back', staged.rows >= 3, `${staged.rows} rows`);
check('sorted against what the object already carries', staged.groups.length >= 2, staged.groups.join(' | '));
check('and the save button counts what is ticked', /Save \d+ changes?/.test(staged.cta), staged.cta);
await onlyBlue('6. proposed', 'Save ');

await page.click('#btnSaveChangeset');
await page.waitForFunction(() => !!document.getElementById('btnCtaUpload'), null, { timeout: 10000 });
const savedTags = await page.evaluate(() => {
  const k = Object.keys(localStorage).find(x => x.startsWith('photomap:changes:'));
  return k ? JSON.parse(localStorage.getItem(k)).tags : null;
});
check('saving writes the staged edit to this browser', savedTags && Object.keys(savedTags).length >= 2,
  JSON.stringify(savedTags));
check('including the record that you checked it in person', !!savedTags?.check_date);
await onlyBlue('6. saved', 'Next: upload to OpenStreetMap');
check('nothing overflows at the end either', (await overflows(page)).length === 0,
  (await overflows(page)).join(' | '));

check('no uncaught JS errors on the whole path', errors.length === 0, JSON.stringify(errors.slice(0, 2)));

// ---- the same journey in one press -----------------------------------------
{
  const { page: p2, errors: e2 } = await open(browser);
  await pickPhoto(p2);
  await findNearby(p2);
  await selectFirst(p2);
  const t0 = Date.now();
  await p2.click('#btnCtaAuto');
  await p2.waitForTimeout(200);
  check('fast-forward says it is working and cannot be pressed twice',
    /Working/.test(await p2.textContent('#btnCtaAuto'))
    && await p2.locator('#btnCtaAuto[disabled]').count() === 1);
  await p2.waitForFunction(() =>
    document.getElementById('phaseProposeNum').classList.contains('is-done'), null, { timeout: 90000 });
  await settled(p2);
  const ff = await p2.evaluate(() => ({
    done: ['Schema', 'Vision', 'Propose']
      .every(n => document.getElementById(`phase${n}Num`).classList.contains('is-done')),
    open: [...document.querySelectorAll('.accordion-collapse.show')].map(e => e.id),
    rows: document.querySelectorAll('#proposeList .list-group-item').length,
  }));
  check('one press carries the schema, the description and the tagging', ff.done,
    `${((Date.now() - t0) / 1000).toFixed(1)}s`);
  check('and stops at the proposals, where judgement is needed',
    ff.open.includes('phasePropose') && ff.rows >= 3, ff.open.join(','));
  check('the fast-forward run raises no errors', e2.length === 0, JSON.stringify(e2.slice(0, 2)));
}

await browser.close();
done();
