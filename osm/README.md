# osm

**snap-osm** is a single static HTML page that takes one photo, reads the GPS coordinates
out of its EXIF data, places it on an OpenStreetMap map, shows what OpenStreetMap has
mapped around it, and — with your approval, tag by tag — sends corrections back.

What every changeset it makes says about itself, and the division of labour it is built
around: *the mapper identified the object on site and chose what to record; the facts come
from the mapper's own photograph; every tag was reviewed and approved by the mapper; a
language model was used only to format those observations as OSM tags.*

Everything runs in the browser. There is no server of ours: the page is a static file, and
it talks directly to map tiles, the OpenStreetMap API, taginfo, OpenRouter and — only for
an area the API will not serve — the Overpass API.
The photo is sent to whichever vision model you configure and nowhere else.

## Layout

The page is built mobile first, targeting an iPhone held portrait — an iPhone 17 is
402 × 874 CSS px. The base stylesheet is the phone layout; the `min-width: 992px` override
only widens the maps and tightens the padding.

One centred column of phases at every width — there is no page-level map and no split
pane. A small toolbar sits at the top, but it is **ordinary content, not sticky** — it
scrolls away as soon as you move down the page.

**Each map belongs to the phase that needs it**: step 2 has a map of where the photo was
taken, step 3 has a map of the photo and the entities around it. Both are **locked** — no
dragging, no zooming, no wheel, no zoom control — so a swipe over a map scrolls the page
as it should, and the view is always the one the step means to show. They frame themselves
and re-frame when you pick an entity, which is why there is no longer a Fit button.

**Every phase ends with one primary blue button** — the obvious thing to press to make
progress: *Where was it taken?* → *Find what's nearby* → *Use &lt;entity&gt;* →
*Next: describe the photo* → *Next: propose OSM tags* → *Next: upload to OpenStreetMap*.
Secondary actions stay outlined so they never compete with it. Committing an entity goes
**straight to extraction**: step 4 is reference material, offered as an outlined
*Inspect the tag schema* beside the primary button, not the next stop.

Stacked buttons sit in a `d-grid gap-2`, so the spacing between them is a property of the
container rather than a margin each caller has to remember — which is how the *Save N
changes again* button came to sit flush against the primary above it.

Buttons follow one convention throughout, so their shape says what they do before the
words are read:

| kind | reads | icon |
| --- | --- | --- |
| moves you to the next step | *Next: &lt;destination&gt;* | trailing `→`, nothing leading |
| does something here | a verb — *Save 3 changes*, *Propose again* | leading icon, no arrow |

**Exactly one button is solid blue at any moment** — the next thing to press —
or none, when the step is waiting for you to pick something. Everything else is
outlined or plainly disabled, and a button that has done its job demotes itself:
*Describe this photo* becomes an outlined *Describe it again* the moment there is
a description, handing the blue to *Next: propose OSM tags*. A disabled
`btn-primary` does not count as demoted, because Bootstrap only fades it and it
still reads as the thing to press; those are outlined instead. The flow suite
checks this at every stop, because it is the invariant that breaks silently as
buttons are added.

The toolbar is the product name on the left — **snap-osm**, with a map-pin mark — and
**Settings** on the right, and nothing else: appearance, the API key, the two models and
the OpenStreetMap account all live inside the dialog. The button carries a visible text
label, not just an icon, and a `title` that spells out what it does.

Colour carries one meaning each and is not spent anywhere else. **Blue** is *press this
next* and belongs to primary buttons and the open phase. **Green, amber and red** are
verdicts the page has reached about a value — valid, check this, cannot be staged — and
stay solid so they read as a judgement. Anything merely descriptive, including the model's
own *high / medium / low confidence*, is an **outline pill in secondary text**: it is
information, not a verdict, and it used to compete with both.

**Appearance** is three states rather than a toggle: *Follow the device*, *Light*, *Dark*.
A plain light/dark switch has no way back to following the device once it has been pressed
once, which is the setting most people actually want; the page also re-resolves when the
device scheme changes underneath it. The choice is remembered per device. It **previews as
you change it and commits on *Save***, like everything else in the dialog — *Cancel* puts
the previous theme back, because a Cancel that silently keeps one of your changes is not a
Cancel.

There is no GeoJSON export. It predated step 7 and answered a question this app no longer
asks: the output is a changeset, not a file.

Within step 3 the order is list, then map, then the details of whatever is selected —
**the detail pane always sits directly under that step's map**. Selecting an entity does
not scroll the page: the map re-frames itself and the details fill in, but the view stays
where the reader put it, so browsing down a list of candidates is not interrupted by the
page jumping. Scroll to the map when you want to look at it.

Other phone-specific handling: `viewport-fit=cover` plus `env(safe-area-inset-*)` so the
Dynamic Island and home indicator do not overlap content; a 2.75 rem (44 px) floor on every
button below the `lg` breakpoint; no nested scroll regions, including the streaming panes,
which grow into the page rather than trapping text behind an invisible iOS overlay
scrollbar; the scale bar is hidden where it would collide with the attribution; and marker
popups are deliberately terse and skipped entirely on phone list selections, because a tall
popup covers most of a short map when the full record is already in the pane below it.

**One selection idiom, everywhere.** Every list you choose from — nearby entities in
step 3, proposals in step 6, staged edits in step 7 — is a `<label>` wrapping a **real
radio or checkbox on the left**, in the same column all the way down the page, and the
whole row is the target. A chosen row is **tinted**, never filled with the primary blue
that means *press this*. Lists you cannot choose from say so by using marks that could not
be controls: step 4's *already set / not set* column is a bare tick or dash, not a circle,
and a proposal that cannot be staged shows a struck-through circle where its checkbox
would be rather than a checkbox that refuses to tick.

Accessibility: every phase header is a real `<button>` that keeps its focus ring when
expanded, the status dot beside it stays green or amber whether or not its phase is the
open one, the six section titles are `<h3>`s, the long-running regions (nearby search,
schema, description, proposals) are `aria-live="polite"`, both maps carry `role="img"`
with a description of what they show, and text clears 4.5:1 against its background in
both themes — Bootstrap's own `.btn-outline-secondary` needed lifting to get there in the
dark one.

## Phases

The page is a vertical accordion, one phase at a time. Each header carries a status
dot — grey for pending, green tick for done, amber for a problem — and a one-line
summary, so the collapsed phases still tell you where things stand. Later phases stay
locked until the earlier ones can supply what they need.

**1 · Photo.** Choose a file, or drop one in. The page handles one photo at a time, so
once it is loaded the upload pane is replaced by a thumbnail with the file name, capture
date, camera and size, and the flow moves on. *Use a different photo* starts over.

**2 · GPS location.** Latitude, longitude, altitude, accuracy, capture time and camera,
plus a deep link to the same spot on openstreetmap.org. The photo appears on the map as a
red camera pin, and the pane says **where the position came from** — the photograph's own
GPS, or your device. A photo without GPS turns the phase amber and keeps phase 3 locked
until you press **Use my current location**; that button is the only thing in the app that
ever reads your position. See *Where the position comes from*, below.

**3 · Nearby entities.** The 10 nearest things OpenStreetMap knows about, businesses and
street furniture alike. See below.

Beside the ordinary next step, once an entity is picked, there is a smaller
**Straight to tags**. Steps 4 to 6 are three presses that always come in the same
order and never take a decision from the mapper — read the schema, describe the
photo, turn that into tags — so that button does all of it and stops at the
proposals, where judgement is actually needed. About four seconds, against three
presses and three waits. It stops at the first thing that goes wrong too, leaving
the failure on screen with its own retry, and each stage's *Stop* ends the run.

**4 · Tag schema.** Once one of those entities is committed to, how that *kind* of thing
is described in OpenStreetMap. See below.

**5 · AI description.** Sends the photo to a vision model with the committed entity and
its schema as context, and streams back an exhaustive description. See below.

**6 · Proposed tags.** Turns that description into OSM tags, sorts them against what the
object already carries, and stages the ones you approve. See below.

**7 · Upload to OSM.** Signs in to OpenStreetMap and sends the staged edits as one
changeset. See below.

## Selecting versus committing

Two different actions, because looking at a candidate and choosing it are different
things:

- **A single click or tap selects** — highlights the point green, draws the connector,
  fills the detail pane. Cheap and reversible; browse as many as you like.
- **A double click or double tap commits** — on the row or on the map point. That locks
  the entity in, unlocks steps 4 and 5, starts fetching the tag schema in the background
  and **opens step 5**, which shows *Getting ready — reading the tag schema* until it
  lands. The step's primary button at the end of the section (*Use &lt;entity&gt;*) does the
  same thing. Once committed, the detail pane grows a **Stop using this entity** button,
  which is the only way back; before that it offers no commit button of its own, so there
  is exactly one primary action per step.

Selection is never delayed waiting to see whether a second tap arrives: the first tap acts
immediately and the second one escalates. Nothing moves under the finger between the two,
because selecting does not scroll the page.

A committed entity keeps a green ring on the map and a green tick in the list, even while
you select other entities to compare against it, and step 3's header changes from
*N shown* to *Using &lt;name&gt;* so the commitment is still legible with the phase collapsed.

## Nearby entities

Every entity in the list is also drawn on the map as an **amber dot**, distinct from the
photo's red pin. Selection is two-way:

- click a **row** and its point turns green and grows, and the map re-frames to fit it
  together with the photo;
- click a **point** and the matching row's radio ticks and it scrolls into view.

Either way a dashed connector is drawn back to the photo and the full details appear in
the pane under the map — category, OSM tag, kind, distance, coordinates, plus address,
opening hours, phone, website and any other tags the element carries, with every raw tag
behind a disclosure. That makes it possible to browse the results one by one and compare
them without losing sight of the map.

- **Businesses / Objects** filters split shops, restaurants, hotels and offices from
  street furniture such as waste baskets, post boxes, benches, hydrants and bus stops.
  Filtering re-plots the map so it always matches the list. Rows are one line each —
  icon, name, category, distance — 41 px rather than the 86 px a two-line row took; the
  Business/Object label lives in the filter, so repeating it per row was noise. A long
  name truncates; the category beside it does not, so it never decays to `S…`.
- The filter and **Wider** sit **below** the list, on a single row. The results are what
  the step is for, so they come first, and one row rather than two keeps more of them on
  a phone screen.
- The search starts at 150 m and widens automatically (400 m, 1 km, 2.5 km) when an area
  is too sparse to fill the list; **Wider** steps it out manually.
- A small set of mapping minutiae is excluded so it cannot flood a dense area —
  surveillance cameras, survey points, antennas, utility poles, manholes, street cabinets
  and street lamps. See `EXCLUDED` in `index.html` to change that.
- The map around the photo is read once, when the phase is first opened, and kept in
  `localStorage` — see below. A spinner runs in the phase header, and the body says
  whether it is reading an area already held or downloading a new one, and reports when
  the radius widens.

## Where the map data comes from

Not Overpass, any more. Overpass is a data-mining service under permanent load, and asking
it a fresh `around` query per photo was the least reliable thing in the app: public
instances refuse outright a good fraction of the time and take seconds when they do not.

Both of the survey editors this app is closest to reached the same conclusion. **Every
Door** never used Overpass — `lib/providers/osm_api.dart` calls `/api/0.6/map?bbox=`
exclusively, over a box from a 1 km radius, and pipes the stream through
`CollectGeometry → StripMembers → FilterAmenities` before storing. **StreetComplete** used
Overpass until v26 and has read the plain API since. That call is what every editor uses
to download its working area: it is CORS-open, needs no token, answers in about a second,
and is the live database rather than a mirror that may be weeks behind.

So the OSM API is the source, and Overpass is kept only as the fallback for the rare area
the API refuses.

Reads always go to **live** OpenStreetMap even when the upload server is set to the
sandbox: the sandbox answers `/map` with an empty document, so there is nothing there to
survey.

### Areas, not questions

The unit is a **slippy-map tile at z14** — about 2.4 km square at the equator and 1.4 km at
54° north. Big enough that a 1 km search usually needs one or two, small enough to stay
well inside the API's 50,000-node ceiling. A search asks for every tile its circle
touches, takes what is already held, downloads the rest at most three at a time, and
filters by distance itself.

The consequence is the one worth having: **a photo whose position falls inside areas
already held needs no network at all.** Measured on the Harrogate example, one bbox call
and two by-id reads cold, then a second photo in the same place answered in 447 ms with
the network switched off entirely.

Entries live under `photomap:tile:1:<z>/<x>/<y>` for **24 hours**, are evicted on read once
past it, and the store is capped at 24 areas with the least recently fetched dropped
first. The source line under the results says how many areas were read, whether they came
from this browser and how old they are, and offers a **refresh** that drops every area
covering the widest search at that position.

### Forgetting it

Areas are held for a day, which is right for *the same photo again* and wrong for *I just
added this in Every Door and want to tag it here*. Two ways out:

- step 3's **refresh** link, which drops every area covering the widest search at that
  photo's position — in context, but only once a search has run;
- **Settings → Cached map → Forget the cached map**, which drops the lot from anywhere.
  It is second in the dialog, above Models, because it is the one control there you reach
  for mid-survey rather than while configuring. It reports what is held (*1 area and 10
  objects held, 46 kB*), acts on the press rather than on *Save*, clears the session's
  record of which areas have been warmed — without that the warm-up would decline to
  re-fetch them — and **re-runs the current search by itself**, since the reason for
  pressing it is almost always "show me the thing I just added". Staged edits and the
  OAuth token are not touched.

### An index, not the objects

A tile stores six fields per element — type, id, latitude, longitude, the one tag that
decides how it is listed, and a display name. Roughly sixty bytes a row.

That choice is what makes the whole thing fit. Measured against the real API:

| stored form | Harrogate, 0.57 km² | central London, 1.15 km² |
| --- | --- | --- |
| raw `/map` JSON | 654 kB | 10.2 MB |
| tagged elements only, ways reduced to a centroid | 77 kB | 2.2 MB |
| filtered to what the list can show | 18 kB | 791 kB |
| **the index actually stored** | **7.7 kB** | **183 kB** |

Full tags would put one central-London tile at 800 kB against a roughly 5 MB
`localStorage` budget. Instead they are read **by id**, batched by type through
`/api/0.6/nodes.json?nodes=…`, for the ten rows on screen and no more — one or two small
requests, cached per element for six hours under `photomap:el:1:<type>/<id>`. One id
deleted since the tile was cached 404s the whole batch, so that case falls back to one
request each and drops whatever has gone.

There is a second, better reason to do it this way: the tags a change is proposed against
are always current, even when the area index is twenty-three hours old.

Ways are collapsed to the centroid of their nodes rather than a bounding-box midpoint —
`/map` returns every node a returned way references, including ones outside the box, so
the real centre is available. Relations are skipped: they carry no geometry of their own
in a `/map` response.

### Warming the area around the photo

Once a photo has a position — from its own EXIF, or from the button in step 2 — step 3 is
going to want the map around it, and you are usually still looking at step 2 when that
becomes knowable. So the areas covering a **500 m radius** are fetched then, quietly,
rather than when *Find what's nearby* is pressed. In practice step 3 opens with nothing
left to fetch.

Keyed on the **photograph**, never on the device: the warm-up must not depend on a
location you have not offered.

It is deliberately unobtrusive: it never reports, never blocks, never competes with a
search you are actually waiting on, runs once per area per session, and stands down
entirely when `navigator.connection.saveData` is set.

### What is disposable, and what is not

A quota error used to wipe every `photomap:` key — including staged edits and the OAuth
token. Map tiles make that a routine event rather than a theoretical one, so eviction is
now restricted to the caches (`schema:`, `tile:`, `el:`, `models:`, `examples:`) and works
oldest-first, retrying the write after each drop. Staged edits and the token are never in
the blast radius.

### When the API will not serve an area

Its limits are 0.25 deg² and 50,000 nodes; over either it answers `400` with the reason in
plain text. Only the densest city tiles get there, and that is exactly where Overpass's
server-side filter earns its keep, so the search falls back to it for that request. The
source line says so, and nothing is cached from a fallback.

Overpass's own failure modes are still handled: two public instances are tried in order,
and mirrors run their own snapshots and can lag badly — at the time of writing
`overpass-api.de` was current to the minute while `overpass.kumi.systems` was **54 days
behind**. When a fallback answers, the page prints which host it was and that host's
database timestamp, in warning colours past a week.

## Tag schema

Committing to an entity fills step 4 with everything known about how that *entity type*
is described, drawn from two sources that answer different questions:

- The **[iD tagging schema](https://github.com/openstreetmap/id-tagging-schema)** is what
  the reference OSM editor puts in front of a mapper. Its preset for the tag gives the
  human name, synonyms, valid geometries, and — the useful part — the ordered list of
  fields the editor offers, which is as close to a definition of *idiomatic* as OSM has.
  Each field is shown with its label, real key(s), value type and example values, and is
  ticked when the selected entity already carries that key, with its current value.
  Optional extra fields sit behind a disclosure.
- **[taginfo](https://taginfo.openstreetmap.org/)** supplies the wiki's prose description
  of the tag, which geometries it is documented for, the combinations the wiki recommends,
  and how often every companion key is *actually* used on objects with this tag — the last
  one shown as a bar per key, which is a good corrective to what the wiki recommends.

Both are best-effort and independent: if one fails the other is still rendered, with a
note saying which is missing. Links to the full wiki page and the taginfo page close it out.

### Caching

The three iD schema files total about 176 kB brotli-compressed. They are fetched at most
once per session, and only on a cache miss.

What goes into `localStorage` is the small **derived** schema — around 11 kB per tag, keyed
`photomap:schema:3:<key>=<value>` with a fetch timestamp and a 30-day TTL — not the raw
bundles, which would not fit. So a repeat visit for a tag already seen renders step 4 with
no network at all. Quota errors are handled by evicting this app's own cached schemas and
retrying once; if that still fails the schema is simply not cached. A **refresh** link
under the results drops the entry and refetches.

## AI description

Step 5 sends the photograph to a vision model through
[OpenRouter](https://openrouter.ai/) and streams the answer back. It never runs on its
own — describing a photo costs money, so it waits for the button.

Two horizontal tabs, deliberately not another accordion, because these are two views of
one operation rather than two steps:

- **Prompt** — exactly the text that will be sent, shown before you run anything, plus a
  note about the attached image. Nothing is hidden.
- **Description** — the answer, streamed. The view moves here by itself when the model
  stops thinking and starts writing. Word count, token counts and cost land underneath
  when it finishes.

Reasoning is still **requested** from models that advertise it — it makes the answer
better — but the trace is **never shown**, here or in step 6. Reading a model's working
out is not useful for this job, and it pushed the answer off the screen. While reasoning
is streaming the status line says *Thinking…* and nothing more.

A **progress bar reports the upload** byte by byte while the photo goes up — `fetch` cannot
report upload progress, so this step uses `XMLHttpRequest`, whose `upload` events give real
byte counts and whose growing `responseText` carries the SSE stream just as well. There is a
Stop button while a request is in flight.

### What the prompt contains

The committed entity supplies context — the photo's coordinates, and what OpenStreetMap
records nearby — explicitly framed as *interpretation only, not something you observed*,
so the model does not parrot it back as though it were visible.

The schema supplies **subjects worth looking at**, as plain English labels drawn from the
preset's fields: Name, Operator, Sports, Hours, Address, Fee, Website, Wheelchair Access
and so on. It deliberately does **not** supply tag syntax or any instruction to emit tags —
the answer wanted here is prose. Fields that can never be read off a photograph (external
registry identifiers such as GNIS, SIRET and VAT numbers, plus editing metadata like
`source` and `fixme`) are filtered out, and the list is capped at 18 subjects, so the
focus list stays photographable.

The rules then ask for exhaustive description, verbatim transcription of every piece of
legible text, an explicit "not shown" rather than a guess, and prose rather than
key/value output.

### Settings

The **Settings** button holds the OpenRouter API key and the model. Both live in
`localStorage` under `photomap:settings:1`.

The dialog is four named sections — **Appearance**, **Cached map**, **Models**,
**OpenStreetMap account** — and within each one every field reads the same way: label, then control, then
the help text explaining it. Nothing is a hint you have to read before you can see what it
is hinting about. Section headings are visually distinct from the field labels beneath
them, every control has a real `<label>` bound to it, and every button carries visible
text rather than a bare icon. The whole dialog commits on **Save**, including the theme.

The key is stored **in plain text** and is sent only to openrouter.ai — anything with
access to the device or to another script on this origin can read it. The settings dialog
says so. Use a key scoped and budgeted for this.

The model picker lists only vision-capable models — those whose
`architecture.input_modalities` include `image`, 183 of OpenRouter's 345 at the time of
writing — with their input price per million tokens and whether they support reasoning.
A filter box narrows the list. The catalogue is cached under `photomap:models:2:openrouter`
for **24 hours**, with a *Reload model list* button to force a refresh.

Neither picker preselects anything: until you choose, both read *— choose a model —*, so
opening Settings just to paste a key cannot silently commit you to whichever model sorts
first. Typing in one picker's filter leaves an unsaved choice in the other alone.

**Tagging reasoning effort** — `off`, `low`, `medium` or `high`, sent as OpenRouter's
`reasoning.effort` on the step-6 call and **defaulting to high**. Step 6 is the step that
rewards thinking: it has to pick from controlled vocabularies and get `opening_hours`
syntax exactly right, and both are the kind of thing a model gets wrong when it answers
quickly. Higher effort costs more and takes longer; models without reasoning support
ignore it, and the chosen level is shown next to the model name in step 6.

### Image size

The photo is re-encoded before sending, at **1536 px on the long edge, JPEG quality 0.70**.
No setting, no prompt — it just happens.

Those numbers were measured rather than picked. The test photo (a wall sign shot at
4284 × 5712, 4.1 MB) was rendered at a range of sizes and OCR'd, counting how many of the
sign's phrases came back — coarse headline through to the smallest print:

| long edge | 512 | 768 | 1024 | 1280 | **1536** | 2048 | 2560 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| phrases read | 3 | 6 | 7 | 11 | **12** | 12 | 12 |
| kB @ q85 | 35 | 77 | 135 | 200 | 278 | 466 | 680 |

Below 1280 the small print is gone. Above 1536 nothing further is recovered, so 2048 and
2560 were paying for pixels nobody can read.

Quality turned out to be a nearly free axis. At 1536 the OCR score is **identical from q90
down to q55** while the file shrinks from 358 kB to 137 kB — legibility here is bound by
resolution, not compression. q0.70 sits in the middle of that flat region.

The two knobs do different jobs, which is worth keeping straight:

- **pixel dimensions** drive the image *tokens* the model bills for;
- **JPEG quality** drives the *bytes* uploaded off a phone.

Result: 4.1 MB → **185 kB at 1152 × 1536**, a 23× reduction. OCR run over the exact bytes
that go on the wire still recovers the finest line on the sign — *"Apologies we may have to
close the facility at short notice due to bad weather or staff shortages"*. Since a vision
model generally reads worse-quality images better than Tesseract does, that is a
conservative floor.

A byte-budget backstop covers photos busier than the test one: if 1536 px at q0.70 still
exceeds 400 kB, quality steps down to 0.60 then 0.50. Resolution is never sacrificed,
because that is the axis legibility actually depends on.

## Proposed tags

Step 6 takes the description from step 5 and asks a **second, separate model** — its own
setting, chosen independently of the vision model — which OSM tags that description
supports. It reads text, not the photo, so any model will do.

### What it is given

- the object's identity and **every tag it already carries**, so it can tell new from changed;
- the **schema**: each key the reference editor offers for this kind of object, with its
  type and **every permitted value, never a sample**. A truncated list reads as permission
  to invent the rest, and the model cannot tell what it was not shown, so nothing is
  elided — all 60 values of `sport`, all 41 of `payment:`. The prompt says explicitly that
  the lists are complete;
- **which of those vocabularies are controlled**. iD says so directly — `customValues:
  false`, or a checkbox or radio widget with no free-text path — so those keys are marked
  *ONE OF these values, and nothing else*, and the model is told that a value outside the
  list is simply wrong and that proposing nothing beats inventing something. Everything
  else is marked *usual values*, where a listed value is preferred but the photograph can
  overrule it. The values given are the raw tag values, with the English label in
  parentheses where it disambiguates (`multi (Unspecified Other Sports)`); an earlier
  version passed the display names through as if they were the values, which told the
  model that `building` accepts "Unspecified Building Type";
- the **documentation**: the wiki's description of what the tag means;
- **how often each companion key is really used** on objects with this tag, including the
  most common values where taginfo reports them (`building` and `building=yes` are separate
  rows there, and conflating them made one key appear several times at different figures);
- **idiomatic examples** — the tag sets of the most thoroughly tagged real objects of the
  same kind near the photo. The wiki says what a tag means but never shows what a
  well-tagged instance looks like; real neighbours do, and they carry regional convention
  with them, which matters for `opening_hours` and addresses. They come from a bounding-box
  Overpass query (a 30 km `around` times out), cached for 30 days.

### What the mapper adds

Above the run button is a fold, **closed by default**, holding a note field that
starts one line tall and grows as you fill it. Most runs never open it, and open
it pushed the run button and the proposals below the fold on a phone. A note
steers the model whether or not the fold is open, so when there is one the closed
summary says *your note is included* — otherwise the proposals would change for
reasons nothing on screen explains.
It is for what the photograph cannot carry: *"the name is misspelled, it should be
Pavilion"*, *"the side door is step-free"*, *"the sign is out of date, they told me they
open at nine now"*.

This is not a hint. The prompt introduces it as coming from someone who was standing in
front of the object, tells the model to weigh it as first-hand observation alongside the
description, to follow any instruction in it, and that **where it contradicts the
description the mapper is right**. Without that, the standing rule — propose nothing the
description does not state — would make the note unusable, since by definition it says
things the photograph does not show. When a note is present the no-inference rule widens
to admit the mapper as a source, and evidence may be quoted from either.

The Prompt tab updates as you type, before anything is sent, so what the note does is
visible rather than implied. An empty note adds nothing to the prompt at all.

After a run the button becomes **Propose again**: edit the note, press it, and the
proposals below are replaced. Steering it a second or third time is the expected way to
use this, not an error path.

### What the model returns is filtered, not merely requested

The prompt says what to ask for. It does not constrain what comes back, and a model
answering in good faith still crosses lines the project has drawn. So every proposal is
checked before it is shown, at one of three severities.

**Blocked** — the checkbox is disabled and the value cannot reach a changeset whatever
else happens:

| what | why |
| --- | --- |
| `name:de`, `int_name`, `loc_name`… | Machine-translated names have drawn DWG blocks three times since 2023. Nothing here can tell a transcription of a bilingual sign from a translation, so neither is accepted; add it by hand if the sign really says so. |
| `wikidata`, `wikipedia`, `*:wikidata` | Identifies the object in another database. Not readable off a photograph, so it would be recalled knowledge. |
| `description`, `note`, `fixme` | Free prose about an object is not verifiable. This is exactly what the September 2024 thread was shot down over. |
| `source`, `source:*` | Provenance goes on the changeset, which snap-osm fills in already. |
| `check_date`, `survey:date`… | A fact about the visit, not the photograph. snap-osm sets it itself. |
| `ref:*`, `gnis:*`, `siret`, `fhrs:*` | An identifier from an external register cannot be observed on site. |
| anything in iD's `discarded.json` | OpenStreetMap strips these on edit. |
| a value outside a **closed** vocabulary | The reference editor refuses it and consumers ignore it, so it is not a judgement call — it is wrong. The allowed values are listed. |

**Flagged** — unticked with the reason shown, but still the mapper's call:

- **deprecated** — checked against iD's `deprecated.json` (503 rules, `*` wildcards
  resolved). The replacement iD specifies is offered behind a *use it* link; a
  multi-key replacement becomes several proposals rather than silently dropping the
  ones that do not fit.
- **not in the evidence** — for keys whose value has to be legible on the object
  (`name`, `operator`, `brand`, `website`, `phone`, `addr:*`, `ref`…), the value is
  looked for in the evidence the model quoted, the mapper's note and the description,
  compared loosely enough to ignore case, punctuation and URL scheme. A value that is
  nowhere in any of them came from somewhere other than the photograph. **This is the
  check that catches the worst failure mode** — a plausible, correct-looking `website`
  or `phone` recalled from training data, which the mapper cannot warrant under the
  contributor terms.
- **off-schema** — the reference editor does not offer this key for this kind of
  object. Allowed, but worth a second look.

`deprecated.min.json` and `discarded.min.json` are 6.7 kB together over the wire and are
fetched once per session.

### How long a tag may be

255 UTF-8 codepoints, for both the key and the value. The
[API page](https://wiki.openstreetmap.org/wiki/API_v0.6) is the precise
statement — the limit covers *"object, changeset and user preference tags, and
relation member roles"* — and codepoints is the operative word: 200 emoji are
200 characters and 400 UTF-16 units, so a value counted with `.length` would be
refused here and accepted by the server.

Nothing is truncated. Half a website address or half a name is worse than no
edit, and nothing in the value says where it was cut, so an over-long proposal
is blocked outright and says so. The check sits *after* the policy rules, not
before: a key that is blocked anyway should say why it is blocked rather than
merely that it is long.

Three other places write tags, and each is bounded:

- the **changeset comment**, which is a tag like any other. `maxlength` is the
  backstop and a counter appears in the last sixty characters; a comment that
  somehow gets past both stops the upload *before* a changeset is opened, naming
  the tag and both numbers, rather than arriving as a 400.
- the **generated comment**, built from the object's name — and an OSM name can
  be 255 on its own. This is the one place the app shortens anything: the name
  gives way, because the rest of the sentence is what makes the comment useful.
- the **provenance string** the app puts on every changeset, which is 231
  characters. Close enough that a sentence added to it would fail as a 400 with
  nothing on screen to explain why, so it is asserted at build time.

### The visit is itself a contribution

Above the save button is a `check_date` row, ticked by default, dated **from the EXIF
capture time** rather than from when the upload happens. It is not a model proposal —
nothing reads a survey date off a photograph — so snap-osm offers it directly.

This matters most in the case that used to be a dead end: walk to a place whose tags are
already perfect, and the model correctly proposes nothing. That is the most common survey
outcome and a genuinely useful one — `check_date` is on 3.3M objects, and confirming a
2009-vintage POI is still right in 2026 is real data. Step 6 now says so and still lets
you save.

Following StreetComplete's `ResurveyUtils`, a fresh survey mark supersedes the older
spellings (`lastcheck`, `last_checked`, `survey:date`, `survey_date`) rather than leaving
the object carrying two dates that disagree; they are removed in the same changeset.

### The response format

The model answers in **JSON whose content is OSM keys and values**. Straight `key=value`
prose would need brittle parsing; a bespoke format would need translating. JSON supplies
only the envelope — requested through OpenRouter's `json_schema` structured output, so it
is schema-checked at the source — while the vocabulary inside stays OSM's own. It also
carries two things a bare tag list could not: the **evidence** for each fact, quoted from
the description, and a **confidence**.

Prompt and the structured response each get a tab, as in step 5. The reasoning trace is
requested — at high effort by default, see Settings — but never displayed.

### opening_hours

`opening_hours` is the one value a model gets wrong in ways that look right: it is a real
grammar, and `Mon-Fri 9am-5pm` is not it. Two things guard it.

The prompt **teaches the grammar** — two-letter day abbreviations, 24-hour `HH:MM`,
commas within a day, semicolons between days, `off`, `24/7`, seasons first — and warns
that the answer is machine-validated.

Then it actually is. Every proposed value on an hours key is run through
[opening_hours.js](https://github.com/opening-hours/opening_hours.js), the reference
implementation the OSM tooling uses. It is 146 kB brotli, most of it holiday tables, so it
is **loaded lazily** — only when a proposal carries such a key — with an SRI hash. Three
outcomes:

Every flag is shown, not merely the first. A value can be both a key the editor
does not offer *and* absent from the description; being told only about the first
leaves the second to be discovered after the decision is made. The one exception
is at the end of the check: a proposal that cannot be staged at all has no use
for advice about how to improve it, so blocks suppress the advisories.

| verdict | badge | what happens |
| --- | --- | --- |
| parses cleanly | green **valid** | ticked, stageable, nothing else to do |
| parses with warnings | amber **check syntax** | **unticked**, the validator's own message is shown, and `prettifyValue()`'s canonical form is offered behind a *use it* link |
| does not parse | red **invalid syntax** | the parse error is shown, the checkbox is **disabled**, and the value cannot reach the changeset whatever else happens |

The canonical form is offered, never applied for you: `Mo-Fr 9-5` prettifies to
`Mo-Fr 09:00-05:00`, which is syntactically clean and factually wrong. Applying it
re-validates the rewritten value, and only the value changes — the evidence quoted from
the photo stays as transcribed.

### Where each value came from

"Is `sport=padel` a real OSM value, or did the model make it up?" is the question a mapper
actually has reading these rows, and the page used to answer only its negation: a value
outside a *closed* vocabulary was blocked, and everything else looked identical.

Most OSM keys are open by design — you may coin `cuisine=georgian` and be right — so this
is **provenance, not a verdict**, and every one of these is an outline pill rather than
one of the solid badges the validators use. Three sources, in descending order of how much
they settle the matter:

| badge | what it means |
| --- | --- |
| **from a fixed list** | the field is closed and this value is one it accepts. Nothing else is legal, so the list settles it. |
| **a suggested value** | the field is open, but the reference editor offers this value — idiomatic, even though others are legal. |
| **used 17k× in OSM** | not on the editor's list, but taginfo says the wider database is full of it. Established practice iD merely does not enumerate. |
| **used 3× in OSM** | neither offered nor much used. Amber, with a note naming the part of the value that is unusual. |
| **never used in OSM** | no object anywhere carries this. The key is open so a new value is *allowed*, but the model may simply have coined it. |
| **free text** | a name, a URL, a phone number, opening hours — there is no vocabulary to check against. |

For a semicolon list like `sport=padel;kubb` each part stands on its own, and the weakest
decides: one invented value among three is still an invented value. The note names which
part it was.

The editor's list is consulted first, so the ordinary case costs **no network at all** —
taginfo is asked only about the values that are not on it, once each, cached for 30 days
under `photomap:values:1:<key>=<value>`.

A key the schema does not offer at all still gets its value checked, and that is where an
invented term is most likely, since nothing upstream constrained the model. But only when
the value *looks* enumerated — lowercase, snake_case, no spaces. Asking taginfo about a URL
or a sentence would produce a frightening *never used in OSM* about something that was
never a vocabulary in the first place.

The worked example is `access=customer`. It is not obviously wrong; it is the singular of
a value OSM really does use. Two million objects say `customers` and none say `customer`,
and that is the only thing that gives it away.

### How a proposal reads

One row is one tag, and it is laid out as one:

```
[x] addr:city=Harrogate                                       high
    off-schema   not in the description
    “Below the legend, in smaller black text: 'Valley Gardens |
     Harlow Moor Drive | Harrogate | HG2 0JT'.”
    ▸ Why these 2 flags
```

Four decisions, each fixing something that made the list hard to read down:

- **Key and value are adjacent**, as `key=value`. They used to sit on separate
  lines with the badges wedged between them, so the two halves of the one thing
  being proposed were the two things furthest apart on the row.
- **Flags get a line of their own.** Mixed in beside the key they wrapped
  differently on every row.
- **Confidence is a word in the margin** — `high`, `med`, `low`, with the meaning
  in its tooltip. It is the model's opinion of itself, the least important thing
  on the row, and at "medium confidence" it was the widest badge on it.
- **The prose folds away.** The badge already names the problem in two words; the
  paragraph explaining it is what made rows tall and ragged, and there can now be
  several. Two things stay out of the fold because neither is explanation: the
  fact that a row **cannot be staged**, and the **button that fixes it**. Reading
  why is one tap; acting, and knowing the consequence, are not.

A value longer than 80 characters is shortened *for display*, with the whole of
it in the tooltip and in the XML preview. Three hundred characters of a value
that is being rejected anyway pushed every other row off the screen.

Two badge weights, and only two: **solid red** is *this cannot go*, an **amber
outline** is *look at this*. Advice used to be solid amber as well, so a key the
editor merely does not list shouted as loudly as a value that will not parse.
*Not in the description* is the softest of these on purpose — the description is
a summary, and a mapper who was standing there often knows exactly why the value
is right, so it says so and asks for a glance rather than an alibi.

### Reviewing and staging

Each proposed fact is sorted against the object's current tags into **New**, **Changes to
existing** (showing the value it would replace) and **Already correct** (shown for
completeness, not selectable). Every actionable one has a checkbox, ticked by default
unless the hours validator has something to say about it; the save button counts what is
selected.

Within each group the rows you can act on come **first**, and the ones you cannot — already
correct, or blocked by the output filter or the hours validator — sink to the bottom and
show a mark in place of a checkbox rather than a checkbox that will not tick.

**Two proposals for the same key are mutually exclusive.** A model asked to describe a
sign can return `website` twice with different values; both used to be tickable and the
last one silently won. Ticking one now unticks the other and each says, under its value,
that another proposal offers the same key.

Once something is saved, the step's primary button changes from *Save N changes* to
**Next: upload to OpenStreetMap →**, with saving again demoted to an outlined button. The
step has done its job; the exit should be the loudest thing in it.

Saving writes a changeset entry to `localStorage` under
`photomap:changes:1:<type>/<id>`, holding the chosen tags, the value each one replaces,
and provenance — which photo, its coordinates, and which two models were involved.
Staging the same object again merges rather than overwrites. Nothing is sent anywhere at
this point; step 7 does that.

## Upload to OpenStreetMap

Step 7 is the only one that writes anything. It is also the only one that does not belong
to the current photo: it reads whatever has accumulated in `localStorage`, so it is live
on a cold page with no photo loaded, and edits from several outings go up together.

### Signing in

OpenStreetMap speaks OAuth 2.0 with PKCE, and both its token endpoint and its write API
send permissive CORS headers, so a static page can do the whole handshake itself — no
server, no client secret, no proxy.

The client ID cannot be baked into the page: OSM matches the redirect URI **exactly**, so
it belongs to wherever this copy is hosted. Settings therefore asks for one, and shows the
two strings needed to register it:

- the **redirect URI**, which is this page's own URL with no query or hash;
- a **description** — *"snap-osm: edits drawn from photo evidence collected and
  corroborated in person by the mapper."*

Register at `/oauth2/applications/new` on whichever server you picked, tick **write_api**
and **read_prefs**, and leave *Confidential application* **unticked** — this is a public
client. Those are the only two scopes requested.

**Sandbox is the default.** `master.apis.dev.openstreetmap.org` is a separate copy of
OpenStreetMap with its own accounts, applications and tokens, and nothing on it reaches
the real map. Switching to live is a deliberate act, and both settings and step 7 say
plainly which one you are pointed at. Because the two servers are genuinely separate
installations, the client ID and the token are stored per server.

The token lands in `localStorage` under `photomap:osm:1:<server>`, in plain text, with the
same exposure as the OpenRouter key: anything that can run script on this origin can edit
the map as you. Signing out deletes it. Note that signing in navigates away and back,
which reloads the page — staged edits survive, a half-finished photo does not, so it is
worth connecting before you start.

Signed out, step 7 leads with a primary **Connect an OpenStreetMap account** and hides
the comment box, the XML preview and the upload button — there is nothing to review until
there is somewhere to send it. The queue itself stays on screen, because discarding
staged edits is something you may reasonably want to do without signing in at all.

### Choosing what goes

**One object per changeset.** Everything staged is listed, grouped by the object it
targets, but the objects are a **single choice** rather than a multi-select: only the
chosen one shows its tags, and only its tags are sent. The changeset guidance asks that a
changeset be local and that its comment describe what is in it, and weeks of edits
collected across a city satisfy neither — the bounding box spans places the mapper never
touched and no honest one-line comment covers the contents. Switching objects remembers
which of their tags you had unticked.

Within the chosen object every tag has a checkbox. Each row shows the value it would write
and, for a change, the value it would replace. The button names the object and counts
exactly what will be sent.

The changeset comment is pre-filled and editable; an upload with an empty comment is
refused, because a comment is what a reviewer reads first.

### Seeing it before you send it

Under the comment field is the **exact XML**, both documents, pretty-printed and
syntax-highlighted, rebuilt on every toggle. Every layer above it is an abstraction over
two XML files and the mapper is the one signing their name to them, so they are shown by
default rather than hidden behind a link.

It is the real thing, not a reconstruction: selecting an object reads it from the API —
anonymously, since OSM serves element reads without a token — so the version number,
coordinates and carried-over tags in the preview are the ones that will be uploaded. Untick
a tag and it disappears from the diff; type in the comment and it appears in the changeset;
switch objects and it re-reads. If the read fails the pane says so plainly and notes that
the upload will read the object again rather than send anything built on a guess.

The preview also earned its keep immediately: it showed the previous editor's `timestamp`,
`user` and `uid` being echoed back to the server. The API ignores them, but sending the last
editor's name back at it is noise, and they are now stripped.

The highlighter is about fifteen lines — escape first, then wrap attributes, then tags, so
the markup it inserts cannot match its own output. Colours come from the Bootstrap semantic
palette, so they track the theme. The blocks use `pre-wrap` rather than `pre`: a
230-character method value scrolled off the right of a phone is not reviewable, and
losing the alignment of wrapped continuations is the cheaper loss.

### What is actually sent

One changeset, tagged:

| tag | value |
| --- | --- |
| `comment` | yours |
| `created_by` | `snap-osm 1.0` |
| `source` | `survey` — the documented value for "I took the pictures myself" (2.7M uses; `survey;photo` invents a value with 129) |
| `snap-osm:method` | who did what, in that order: mapper identified and chose, photo supplied the facts, mapper approved every tag, model only formatted |
| `snap-osm:models` | **only if you ask for it in settings** — see below |

Then one `osmChange` diff for every object at once, and a close. The sequence matters:

1. **Read the live elements first.** This gives the current version number, the current
   tags to merge onto, and — the trap in a tag-only edit — the element's children. The API
   replaces what it is given, so a way uploaded without its `<nd>` refs loses its geometry.
   Everything is fetched and rebuilt before a changeset is opened, so a problem costs
   nothing.
2. **Detect conflicts.** Each staged tag records the value the object carried when it was
   staged. If the live value differs from that *and* from what we would write, somebody
   else has been there since. The whole upload aborts before opening a changeset, the
   affected tags are unticked, the row says what changed, and nothing is discarded. Press
   upload again to send the rest.
3. **Create, upload, close.**
4. **Only then forget them** — and only the tags that actually went. Anything left unticked
   stays staged rather than being silently binned. A failure at any point leaves everything
   in the browser, and says so.

**Naming the models is off by default.** The changeset already says a language model
formatted the observations and that you approved every tag, which is the part a reviewer
needs; the exact model ids add detail nobody asked for, and no convention exists for
publishing them. There is a settings toggle for when there *is* a reason — a wiki page
describing a particular setup, or a discussion where someone asked.

On success the changeset **opens in a new tab** and the link stays on the page. The tab is
opened without `noopener` and then has its `opener` severed by hand: `window.open(url,
'_blank', 'noopener')` returns `null` by specification, so there would be no way to tell
"opened" from "blocked by the browser" — and the result line says which happened.

### Afterwards

Nothing is opened for you. On a phone a new tab dropped on you mid-survey is how you lose
your place, so the changeset is offered instead:

- with objects still staged, the link sits **below** the upload button as a secondary
  action and the note says which changeset is away and how much is left;
- with the queue empty, the link becomes the step's **primary** action, beside an outlined
  *Start again with another photo* that resets the page and scrolls back to the top.

### A changeset left open by a failed upload

Uploading is three calls — open a changeset, post the diff, close it — so a
failure at the second leaves an empty changeset open on the mapper's account.

**It cannot be deleted.** The API is explicit: *"it is not possible to delete
changesets at the moment, even if they don't contain any changes."* The only
operation is `PUT /api/0.6/changeset/#id/close`, and left alone the server
closes it after an hour idle, or twenty-four hours, whichever comes first.

So the page closes it itself, the moment the upload fails, without being asked —
and says which changeset and that it went in empty. If that close *also* fails,
the id is remembered in `localStorage` (a failed upload is exactly when somebody
reloads) and step 7 grows a warning offering to close it, explaining why it
cannot simply be deleted. Anything remembered from a previous sitting is checked
once on load and forgotten silently if the server has already closed it.

### Throwing edits away

Every staged object has a discard control, and there is one for all of them at once. Both
take **two taps**: the first arms the button and says *Really discard?*, the second does
it, and an armed button disarms itself after five seconds. Nothing is recoverable
afterwards, so the confirmation is the point — but a modal for something this small is
worse than a button that asks once. The notice afterwards says how many went and that
nothing was sent to OpenStreetMap.

## Where the position comes from

Two sources, in that order: the photograph's own EXIF GPS, and failing that **your
device's live position**.

### Getting GPS data off an iPhone

iOS only hands a photo's location data to a web page if you ask it to, per upload:

1. Tap **Choose a photo** and pick **Photo Library**.
2. Tap **Options** at the bottom-left of the picker.
3. Turn **Location** on, then select the photo.

A photo captured through the picker's **Take Photo** option never carries GPS, regardless
of that setting. Neither does one taken while the phone has no recent fix — the camera
writes GPS only if it has a position at the moment of the shot, which after a cold start,
indoors, or straight out of a pocket it often does not.

### Your location, only ever on request

Two rules, and they are the whole design:

- **Nothing is asked for until a button is pressed.** No prompt on load, no permission
  query on load, no watch running in the background. A page that asks for your position
  before you have shown it anything has not earned the question, and on iOS a refused
  prompt is expensive to undo.
- **Nothing is applied without a press either.** *Where the phone is now* is a guess about
  where a photograph was taken, and a wrong one puts an edit somewhere you never went. It
  is offered; it is never assumed — not even for a photo taken sixty seconds ago.

One reading, not a watch. `getCurrentPosition` runs once, and the first good fix
(accurate to 200 m or better) is kept for the rest of the session and reused. Holding the
GPS open past that costs battery to answer a question nobody asked again. A second photo
needing a position gets the fix already in hand, with no second read.

The only place in the app that reaches for the device position is the **Use my current
location** button in step 2, and only when the photo it is looking at has no GPS of its
own.

### How a photo gets a position

| the photo | what happens |
| --- | --- |
| has EXIF GPS | that is used, always. A device fix never overrides the photograph. |
| has none | step 2 turns amber, step 3 stays locked, and the way forward is a primary **Use my current location** — pressed, never assumed |
| has none, and you press it | the position is read once, applied, and step 3 unlocks |
| has none, and location is refused or times out | the reason is shown, the button becomes **Try my location again**, and *Choose a different photo* is still there |

The request gives up after **30 seconds**. A cold fix on a phone genuinely takes tens of
seconds and this is the one moment you are waiting on it, but a spinner with no end is
worse than an error.

Whenever a position came from the device rather than the photograph, step 2 says so in as
many words, the header summary is suffixed *(device)*, an **Accuracy** row appears, and
the pane warns you to check that the entity you pick is really the one you photographed.
The distinction matters: a device fix places you, not necessarily the object, and the
whole point of the app is that the two were in the same place at the same time.

Device-specific copy is gated on the hardware rather than shown to everyone: the *Options
→ Location* instructions appear only on iOS, and *double-tap* reads *double-click* on a
pointer-fine device.

## Files

`index.html` is the whole application. `test/` is the verification harness — a
local mirror of everything the page talks to, and four suites over it; see
[TESTING.md](TESTING.md). Bootstrap 5.3, Bootstrap Icons, Leaflet and exifr
load from CDNs with subresource-integrity hashes; there is no build step.
`opening_hours.js` loads the same way but **on demand**, the first time a proposal carries
an hours key, so a run that never reaches step 6 never pays for it. There is no OAuth
library: the PKCE handshake is about forty lines against `crypto.subtle`.

## Deployment

The page is hosted on a [sprite](https://sprites.dev) named `osm`:

```bash
sprite create osm
sprite exec -s osm --file osm/index.html:/home/sprite/site/index.html -- true
sprite exec -s osm -- sprite-services create photomap \
  --cmd /.sprite/bin/python3 \
  --args "-u,-m,http.server,8080,--bind,0.0.0.0,--directory,/home/sprite/site" \
  --http-port 8080
```

Registering the server as a sprite service (rather than backgrounding it from `exec`)
is what makes it durable: the sprite proxy routes traffic to the service's `--http-port`
and starts the service on demand when a request arrives after a sleep.

The URL is restricted to the org (`--url-auth sprite`), so reaching it needs a Sprites
token — `curl -H "Authorization: Bearer $SPRITES_API_KEY"` — or a browser signed in to
the account. `sprite url update --auth public -s osm` opens it to anyone with the link.

To publish an update, re-run the `--file` upload; `http.server` reads from disk per
request, so no restart is needed:

```bash
sprite exec -s osm --file osm/index.html:/home/sprite/site/index.html -- true
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $SPRITES_API_KEY" https://osm-blpqo.sprites.app/
```
