# Testing snap-osm

```bash
cd osm/test
npm install            # playwright, once
./run.sh               # everything, about 30 seconds
./run.sh 03-tags       # one suite
```

`run.sh` starts one mirror per suite and runs them at once, so the wall clock is
the slowest suite rather than the sum. It prints each suite's output in order and
exits non-zero if anything failed.

## What is here

| file | what it covers |
| --- | --- |
| `01-flow.mjs` | the path a mapper walks: photo → GPS → nearby → schema → describe → propose → save, and the fast-forward that does the middle of it in one press |
| `02-data.mjs` | where the map comes from: tiles from the OSM API, the index that is stored, tags read by id, the store's bounds, forgetting it, and the device location |
| `03-tags.mjs` | what guards the proposal list: the output filter, `opening_hours`, vocabulary provenance, duplicate keys |
| `04-upload.mjs` | OAuth, conflict detection, the exact osmChange bytes, and every way a send can fail |
| `lib.mjs` | the shared drive, the page-reading helpers, the reporter |
| `mirror.mjs` | a local stand-in for everything the page talks to |

182 checks. Not an inventory of the interface — the behaviour has settled, and a
test per pixel costs more to maintain than it catches. What is here is the
sequence, the guards, and everything that could lose a mapper's work or put a
bad edit on the map. For anything else, drive it by hand: see below.

## No test edit can reach OpenStreetMap

The mirror rewrites **both** OSM origins — `api.openstreetmap.org` and
`master.apis.dev.openstreetmap.org` — to itself, and answers with an
OpenStreetMap that lives in memory. `04-upload.mjs` refuses to start if any real
OSM origin survives in the page it was given, so pointing it at the deployed
site exits 2 rather than uploading anything.

The two exceptions are read-only and harmless: `wiki.openstreetmap.org` and
`taginfo.openstreetmap.org`.

## The mirror

It fetches the page under test from the sprite, rewrites every URL the page uses
to a local one, and stands in for each of them.

**Upstream responses are recorded to `.upstream/` and replayed.** Before that,
the same drive took anywhere from 11 to 39 seconds depending on how busy taginfo
was, and assertions broke whenever somebody edited Harrogate. To refresh the
fixtures deliberately:

```bash
RECORD=1 ./run.sh
```

The page itself is never cached — it is the thing being tested.

**Scenarios are chosen at runtime**, by POSTing to `/_mode`, so nothing has to
restart:

```js
await setMode({ badTags: true });     // the model returns what the DWG blocks people over
await setMode({ oh: 'dirty' });       // hours that parse but not idiomatically
await setMode({ vocab: true });       // values outside the reference editor's lists
await setMode({ osmMoved: true });    // somebody else edited the object first
await setMode({ osmFail: 'upload' });  // the server rejects the diff
await setMode({ osmDeny: true });     // the mapper refuses authorization
await setMode({ osmMapFail: true });  // the API will not serve the bbox
await setMode();                      // back to the defaults
```

`GET /_mode` reports the current scenario and how many upstream responses have
been recorded versus replayed — useful when a suite is unexpectedly slow.

## Driving it by hand

The mirror serves the page at `http://127.0.0.1:8099/`, so anything can be
checked interactively:

```bash
cd osm/test
./restart-tunnel.sh        # the sprite, on :8080
./restart-mirror.sh        # the mirror, on :8099
sprite file push -s osm ../index.html /home/sprite/site/index.html
```

Then a throwaway script. This is the shape almost every investigation took:

```js
import { launch, open, driveToProposals, proposalRows } from './lib.mjs';
const browser = await launch();
const { page } = await open(browser);          // iPhone 17, empty store, keys set
await driveToProposals(page);                  // photo → proposals, about 4 seconds
console.log(await proposalRows(page));
await page.screenshot({ path: 'look.png', fullPage: true });
await browser.close();
```

`Read` the PNG to look at it. A few things worth knowing:

- **Measure, do not eyeball.** `getBoundingClientRect()` and `getComputedStyle()`
  in `page.evaluate` settle arguments that screenshots only start. Two spacing
  bugs in this project were found by comparing `right` against the viewport
  width, and one by reading `marginTop` and finding it was zero.
- **Wait for the accordion.** Bootstrap's collapse takes 350 ms, during which two
  phases are both visible and both answer to `offsetParent`. `settled(page)`
  waits it out; without it, a click can land mid-animation and toggle a phase
  shut again.
- **Screenshot an element, not the page**, when that is the subject:
  `page.locator('#proposeList').screenshot(...)`.
- **Stub the platform** rather than hoping for it.
  `page.addInitScript` replacing `navigator.geolocation.getCurrentPosition` is
  how the refusal and timeout paths are checked; `context.setOffline(true)` is
  how the tile cache is proved to work with no network at all.
- **Count the requests.** `page.on('request', …)` answers "does this cost a round
  trip?" directly, which is how the warm-tile and cached-value claims are made.

## Deploying

The page is served from a [sprite](https://sprites.dev) named `osm`:

```bash
sprite file push -s osm osm/index.html /home/sprite/site/index.html
```

The suites read the deployed copy through the mirror, so **a change has to be
pushed before it can be tested**. More than one confusing failure in this project
was a stale deploy.
