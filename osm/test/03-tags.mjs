// What the model returns is filtered, validated and sourced before the mapper
// is asked to approve any of it. Four things guard the list, and each is
// checked against a model output chosen to provoke it:
//
//   the output filter   — keys the community has blocked mappers over
//   opening_hours       — the one value that is wrong in ways that look right
//   the vocabulary      — was this value chosen from a list, or invented?
//   duplicate keys      — two proposals for one key, only one of which can go
//
// One drive, then the mirror's scenario is switched and the tagging call re-run,
// which costs about a third of a second. Driving from a photo for each of these
// took three minutes and told us nothing extra.
import { launch, open, reporter, setMode, driveToProposals, propose,
         proposalRows, row, badge } from './lib.mjs';

const { check, done } = reporter('tags');
const browser = await launch();

await setMode();
const { page, errors } = await open(browser);
await driveToProposals(page);

// ---- the ordinary output: listed values, free text, nothing to block -------
{
  const rows = await proposalRows(page);
  check('the model\'s proposals are shown', rows.length >= 3, `${rows.length} rows`);
  const sport = row(rows, 'sport');
  check('a value the reference editor offers is named as one',
    !!badge(sport, /a suggested value/), sport?.badges.map(b => b.text).join(' | '));
  for (const key of ['operator', 'opening_hours']) {
    check(`${key} is marked free text — there is no vocabulary to check`,
      !!badge(row(rows, key), /free text/), row(rows, key)?.badges.map(b => b.text).join(' | '));
  }
  check('the visit itself is offered as a contribution',
    !!row(rows, 'check_date'), rows.map(r => r.key).join(','));
  // Provenance is information, not a ruling: outline pills, never the solid
  // badges the validators use to say something is wrong.
  const pills = rows.flatMap(r => r.badges)
    .filter(b => /free text|suggested value|fixed list|used |never used/.test(b.text));
  check('provenance badges are outlined, not solid',
    pills.length > 0 && pills.every(b => /border/.test(b.cls) && !/text-bg-/.test(b.cls)));
}

// ---- the output filter -----------------------------------------------------
{
  await setMode({ badTags: true });
  await propose(page);
  const rows = await proposalRows(page);
  const blocked = k => {
    const r = row(rows, k);
    return r && !r.selectable && /Cannot be staged/.test(r.text);
  };
  // Every one of these is something the DWG has blocked mappers over: a
  // translation nobody checked, an identifier that cannot be read off a sign,
  // and prose invented to fill a field.
  check('a name in a language nobody verified cannot be staged', blocked('name:de'));
  check('an identifier that is not in the photograph cannot be staged', blocked('wikidata'));
  check('invented prose cannot be staged', blocked('description'));
  const chair = row(rows, 'wheelchair');
  check('a value outside a closed vocabulary cannot be staged',
    chair && !chair.selectable && /not an allowed value/.test(chair.text),
    chair?.badges.map(b => b.text).join(' | '));
  // Not obviously wrong: the singular of a value OSM really does use. Two
  // million objects say `customers` and none say `customer`.
  const access = row(rows, 'access');
  check('a plausible singular the database spells plural is caught',
    !!badge(access, /never used in OSM/), access?.badges.map(b => b.text).join(' | '));
  check('and the deprecation rule offers the spelling in use',
    /access=customers/.test(access?.text || ''));
  /* Length. The limit is 255 UTF-8 codepoints and it is not negotiable, but the
     interesting half is that it is codepoints: 200 emoji are 400 UTF-16 units,
     so counting with .length would reject a legal value. */
  const long = row(rows, 'operator:short');
  check('a value over 255 characters cannot be staged',
    long && !long.selectable && /allows 255 characters in a tag value and this one is 300/
      .test(long.text), long?.text.slice(0, 90));
  check('and it says why it was not simply shortened',
    /worse than no edit at all/.test(long?.text || ''));
  const emoji = row(rows, 'inscription');
  check('200 emoji are 200 characters, not 400 — the count is codepoints',
    emoji && emoji.selectable, emoji?.text.slice(0, 60));

  /* Absent from the description. Worth saying, but not an accusation — the
     description is a summary, and a mapper who was standing there often knows
     exactly why the value is right. So it is an amber outline rather than a
     solid badge, and it still unticks rather than blocks. */
  const site = row(rows, 'website');
  check('a value absent from the description is flagged but still the mapper\'s call',
    site && site.selectable && !site.checked && !!badge(site, /not in the description/),
    site?.badges.map(b => b.text).join(' | '));
  check('and it is worded as something to glance at, not an accusation',
    /Often there is a good reason/.test(site?.text || ''), site?.text.slice(0, 90));

  /* Every flag, not merely the first. A value can be both a key the editor does
     not offer and absent from the description, and being told only about the
     first leaves the second to be discovered after the decision is made. */
  const many = rows.find(r => r.badges.filter(b => /deprecated|never used|not in the description/
    .test(b.text)).length > 1);
  check('a proposal with two things wrong shows both',
    !!many, rows.map(r => `${r.key}[${r.badges.map(b => b.text).join(',')}]`).join(' ').slice(0, 120));

  // Solid red is reserved for "this cannot go"; advice is an amber outline.
  const solids = rows.flatMap(r => r.badges).filter(b => /text-bg-warning/.test(b.cls));
  check('nothing advisory shouts in solid amber', solids.length === 0,
    solids.map(b => b.text).join(' | '));
}

// ---- the wiki, one tap from every tag ---------------------------------------
// Reviewing a proposal means knowing how the thing is meant to be modelled, and
// nobody carries the schema in their head.
{
  await setMode({ vocab: true });
  await propose(page);
  const links = await page.evaluate(() => ({
    entity: [...document.querySelectorAll('#proposeEntity a')]
      .map(a => `${a.getAttribute('href')}|${a.target}`),
    rows: [...document.querySelectorAll('#proposeList .list-group-item')].map(el => ({
      key: el.querySelector('code')?.textContent,
      hrefs: [...el.querySelectorAll('a.wiki-link')].map(a => a.getAttribute('href')),
      targets: [...el.querySelectorAll('a.wiki-link')].map(a => a.target),
    })),
  }));
  check('the object under review names its own wiki page',
    links.entity.some(l => /wiki\/Tag:leisure%3Dsports_centre\|_blank/.test(l)),
    links.entity.join(' '));
  check('every proposal links its key to the wiki',
    links.rows.length > 0 && links.rows.every(r => r.hrefs.some(h => /\/wiki\/Key:/.test(h))),
    links.rows.filter(r => !r.hrefs.some(h => /Key:/.test(h))).map(r => r.key).join(','));
  check('and all of them open in a new tab',
    links.rows.every(r => r.targets.every(t => t === '_blank')));
  // A Tag: page reliably exists only for a value the editor offers or the
  // database widely uses — otherwise the link would land on "no such page".
  const chair = links.rows.find(r => r.key === 'wheelchair');
  check('a value from a fixed list links to its own page too',
    chair?.hrefs.some(h => /\/wiki\/Tag:wheelchair%3Dlimited/.test(h)), chair?.hrefs.join(' '));
  const coined = links.rows.find(r => r.key === 'cuisine');
  check('a value the model coined links only the key, not a page that does not exist',
    coined && !coined.hrefs.some(h => /\/wiki\/Tag:/.test(h)), coined?.hrefs.join(' '));
  // A colon belongs in a wiki title; Key:name%3Ade is an ugly way to ask for it.
  await setMode({ badTags: true });
  await propose(page);
  const de = await page.evaluate(() =>
    [...document.querySelectorAll('#proposeList a.wiki-link')]
      .map(a => a.getAttribute('href')).find(h => /name/.test(h)));
  check('a key with a colon in it is not over-escaped', /\/wiki\/Key:name:de$/.test(de || ''), de);

  // The rows are labels, so a link inside one must not tick the box it sits in.
  await setMode({ vocab: true });
  await propose(page);
  const toggled = await page.evaluate(() => {
    const el = [...document.querySelectorAll('#proposeList .list-group-item')]
      .find(x => x.querySelector('input') && x.querySelector('a.wiki-link'));
    const box = el.querySelector('input');
    const was = box.checked;
    el.querySelector('a.wiki-link').dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }));
    return was !== box.checked;
  });
  check('following a link does not tick the row it is in', !toggled);
  await setMode();
}

// ---- opening_hours, in its three shapes ------------------------------------
{
  await setMode({ oh: 'clean' });
  await propose(page);
  let oh = row(await proposalRows(page), 'opening_hours');
  check('a syntactically clean value is badged valid and stays ticked',
    /valid/.test(oh.text) && oh.checked, oh.badges.map(b => b.text).join(' | '));

  await setMode({ oh: 'dirty' });
  await propose(page);
  oh = row(await proposalRows(page), 'opening_hours');
  check('a value the validator grumbles about is badged for checking',
    /check syntax/.test(oh.text));
  check('and is not ticked for you, though it can be', !oh.checked && oh.selectable);
  check('the validator\'s own words are shown',
    /Please use notation "Sa,Su" for "weekends"/.test(oh.text));
  await page.click('#proposeList button[data-canonical]');
  await page.waitForTimeout(600);
  oh = row(await proposalRows(page), 'opening_hours');
  // Applying the rewrite must not touch the evidence: "10.00am" is the sign,
  // transcribed, and the sign did not change.
  check('applying the canonical form rewrites the value, not the evidence',
    oh.value === 'Sa,Su 10:00-17:30' && /“Weekends, School holidays[^”]*10\.00am/.test(oh.text),
    oh.value);
  check('and the rewrite re-validates clean and counts', /valid/.test(oh.text) && oh.checked);

  await setMode({ oh: 'broken' });
  await propose(page);
  oh = row(await proposalRows(page), 'opening_hours');
  check('a value that will not parse is badged invalid and locked out',
    /invalid syntax/.test(oh.text) && !oh.selectable);
  check('and it explains what the parser choked on', /will not parse/.test(oh.text));
  await page.click('#btnSaveChangeset');
  await page.waitForTimeout(300);
  const staged = await page.evaluate(() => {
    const k = Object.keys(localStorage).find(x => x.startsWith('photomap:changes:'));
    return k ? JSON.parse(localStorage.getItem(k)).tags : null;
  });
  check('an unparseable value never reaches the store',
    staged && !('opening_hours' in staged), JSON.stringify(staged));
  await setMode({ oh: 'clean' });
}

// ---- reaching outside the editor's value list ------------------------------
{
  await setMode({ vocab: true });
  await propose(page);
  const rows = await proposalRows(page);
  const calls = [];
  page.on('request', r => { if (/key\/values/.test(r.url())) calls.push(r.url()); });

  // sport=padel;kubb — padel is on iD's list, kubb is not, and 3 objects use it.
  const sport = row(rows, 'sport', 'padel;kubb');
  const rare = badge(sport, /used \d+× in OSM/);
  check('a value off the list is reported by how much OpenStreetMap uses it',
    !!rare, sport?.badges.map(b => b.text).join(' | '));
  check('a barely-used value is coloured as something to look at',
    /text-warning-emphasis/.test(rare?.cls || ''));
  check('and the note names the part that was unusual',
    /“kubb” is not among the values/.test(sport?.text || ''));

  // cuisine=nordic_fusion — a key the schema does not offer here, and a value
  // nothing in the database has ever carried. The case this exists for.
  const cuisine = row(rows, 'cuisine');
  check('a value nothing in OpenStreetMap uses is called out',
    !!badge(cuisine, /never used in OSM/), cuisine?.badges.map(b => b.text).join(' | '));
  check('and it says a new value is allowed rather than pretending it is wrong',
    /a new value is allowed/.test(cuisine?.text || ''));
  check('a value from a closed vocabulary says the list is fixed',
    !!badge(row(rows, 'wheelchair'), /from a fixed list/),
    row(rows, 'wheelchair')?.badges.map(b => b.text).join(' | '));

  // Two sport proposals now, and only one of them can be sent.
  const sports = rows.filter(r => r.key === 'sport');
  check('two proposals for one key both appear', sports.length === 2);
  check('and each says only one can be sent',
    sports.every(r => /only one can be sent/.test(r.text)));
  await page.evaluate(() => {
    const boxes = [...document.querySelectorAll('#proposeList input[data-fact]')];
    const el = boxes.find(b => b.closest('.list-group-item').textContent.includes('padel'));
    if (el && !el.checked) el.click();
  });
  await page.waitForTimeout(300);
  const ticked = (await proposalRows(page)).filter(r => r.key === 'sport' && r.checked);
  check('ticking one unticks the other', ticked.length <= 1, `${ticked.length} ticked`);

  await page.waitForTimeout(200);
  check('a cached usage count is not looked up twice',
    calls.length === 0 || new Set(calls).size === calls.length, `${calls.length} lookups`);
  await setMode();
}

check('no uncaught JS errors across every scenario', errors.length === 0, JSON.stringify(errors.slice(0, 2)));
await browser.close();
done();
