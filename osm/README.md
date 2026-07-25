# osm

Photo Map is a single static HTML page that takes one photo, reads the GPS coordinates
out of its EXIF data, places it on an OpenStreetMap map, and shows what OpenStreetMap has
mapped around it.

Everything runs in the browser. The photo is never uploaded — the page is served as a
plain static file and makes no network calls beyond map tiles and the Overpass API.

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
progress: *Where was it taken?* → *Find what's nearby* → *Use &lt;entity&gt;* → *How is this
described?* → *Describe the photo*. Secondary actions stay outlined so they never compete
with it.

Every button carries a visible text label, not just an icon, and a `title` that spells out
what it does:

| Button | What it does |
| --- | --- |
| **GeoJSON** | Downloads `photo-location.geojson` — one Point feature at the photo's coordinates, with its filename, capture time, camera, and the entity you committed to (its OSM id, name, tag and distance). Disabled until a photo with coordinates is loaded. |
| **Theme** | Switches between the light and dark colour scheme. The page already follows the device setting, so this is only an override, and the choice is remembered. |
| **Settings** | OpenRouter API key and the vision model used in step 5. See below. |

The row wraps, so more buttons can be added.

Within step 3 the order is list, then map, then the details of whatever is selected —
**the detail pane always sits directly under that step's map**, so picking an entity
scrolls the map to the top of the viewport and leaves the map and the start of its details
on screen together.

Other phone-specific handling: `viewport-fit=cover` plus `env(safe-area-inset-*)` so the
Dynamic Island and home indicator do not overlap content; ~44 px minimum tap targets; no
nested scroll regions; the scale bar is hidden where it would collide with the
attribution; and marker popups are deliberately terse and skipped entirely on phone list
selections, because a tall popup covers most of a short map when the full record is
already in the pane below it.

## Phases

The page is a vertical accordion, one phase at a time. Each header carries a status
dot — grey for pending, green tick for done, amber for a problem — and a one-line
summary, so the collapsed phases still tell you where things stand. Later phases stay
locked until the earlier ones can supply what they need.

**1 · Photo.** Choose a file, or drop one in. The page handles one photo at a time, so
once it is loaded the upload pane is replaced by a thumbnail with the file name, capture
date, camera and size, and the flow moves on. *Use a different photo* starts over.

**2 · GPS location.** Latitude, longitude, altitude, capture time and camera, plus a deep
link to the same spot on openstreetmap.org. The photo appears on the map as a red camera
pin. If the photo carries no coordinates the phase turns amber, explains the iPhone
Location toggle, and phase 3 stays locked.

**3 · Nearby entities.** The 10 nearest things OpenStreetMap knows about, businesses and
street furniture alike. See below.

**4 · Tag schema.** Once one of those entities is committed to, how that *kind* of thing
is described in OpenStreetMap. See below.

**5 · AI description.** Sends the photo to a vision model with the committed entity and
its schema as context, and streams back an exhaustive description. See below.

More phases will be added after these.

## Selecting versus committing

Two different actions, because looking at a candidate and choosing it are different
things:

- **A single click or tap selects** — highlights the point green, draws the connector,
  fills the detail pane. Cheap and reversible; browse as many as you like.
- **A double click or double tap commits** — on the row or on the map point. That locks
  the entity in, fetches its tag schema, and unlocks step 4. The step's primary button at
  the end of the section (*Use &lt;entity&gt;*) does the same thing, as does the smaller
  **Use this entity** button in the detail pane; once committed that button becomes
  *Stop using this entity*, which is the only way back.

Selection is never delayed waiting to see whether a second tap arrives: the first tap
acts immediately and the second one escalates. The map scroll that follows a selection on
mobile *is* deferred past the double-tap window, though — scrolling the list out from
under a finger would make the second tap impossible to land.

A committed entity keeps a green ring on the map and a green tick in the list, even while
you select other entities to compare against it.

## Nearby entities

Every entity in the list is also drawn on the map as an **amber dot**, distinct from the
photo's red pin. Selection is two-way:

- click a **row** and its point turns green and grows, and the map re-frames to fit it
  together with the photo;
- click a **point** and the matching row goes active and scrolls into view.

Either way a dashed connector is drawn back to the photo and the full details appear in
the pane under the map — category, OSM tag, kind, distance, coordinates, plus address,
opening hours, phone, website and any other tags the element carries, with every raw tag
behind a disclosure. That makes it possible to browse the results one by one and compare
them without losing sight of the map.

- **Businesses / Objects** filters split shops, restaurants, hotels and offices from
  street furniture such as waste baskets, post boxes, benches, hydrants and bus stops.
  Filtering re-plots the map so it always matches the list. Rows are one line each —
  icon, name, category, distance — 41 px rather than the 86 px a two-line row took; the
  Business/Object label lives in the filter above, so repeating it per row was noise.
- The search starts at 150 m and widens automatically (400 m, 1 km, 2.5 km) when an area
  is too sparse to fill the list; **Wider** steps it out manually.
- A small set of mapping minutiae is excluded so it cannot flood a dense area —
  surveillance cameras, survey points, antennas, utility poles, manholes, street cabinets
  and street lamps. See `EXCLUDED` in `index.html` to change that.
- Overpass is queried once, when the phase is first opened, and the result is cached both
  in memory and in `localStorage` — see below. A spinner runs in the phase header, and the
  body reports the radius being searched and says so when it widens.

### Caching the Overpass answer

Picking the same photo again asks the same question of the same coordinates, so the answer
is kept in `localStorage` for 24 hours under
`photomap:nearby:1:<lat>,<lon>@<radius>`, coordinates rounded to 6 decimal places
(~11 cm — far finer than any phone's GPS, and stable across re-picks of one photo). Each
radius is cached separately, so **Wider** benefits too, and re-narrowing costs nothing.

Distances are deliberately *not* stored. They are recomputed against whichever position is
asking, so a second photo taken a few metres away reuses the same cached features and
still gets its own correct distances and ordering.

Measured on the Harrogate example: **16.5 s cold, 0.4 s from cache**, no Overpass traffic
at all on the second run, for 9 kB of stored data covering all 36 features found. The
source line under the results says when the data came from cache and how old it is, and
offers a **refresh** that drops the entries for every radius at that position and refetches.
Entries past the 24-hour TTL are evicted on read rather than left to accumulate.

### Which server answered, and how old its data is

Overpass is a free shared service and its public instances refuse requests when busy, so
the page tries a second instance before giving up, and offers a retry rather than failing
silently. That fallback matters for correctness, not just availability: mirrors run their
own database snapshots and can lag badly. At the time of writing `overpass-api.de` was
current to the minute while `overpass.kumi.systems` was **54 days behind** — enough that a
recently mapped feature is missing entirely from one and first in the list on the other.

The page therefore prints which host answered and that host's database timestamp beneath
the results, and flags it in warning colours when the data is more than a week old.

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

What goes into `localStorage` is the small **derived** schema — around 5 kB per tag, keyed
`photomap:schema:1:<key>=<value>` with a fetch timestamp and a 30-day TTL — not the raw
bundles, which would not fit. So a repeat visit for a tag already seen renders step 4 with
no network at all. Quota errors are handled by evicting this app's own cached schemas and
retrying once; if that still fails the schema is simply not cached. A **refresh** link
under the results drops the entry and refetches.

## AI description

Step 5 sends the photograph to a vision model through
[OpenRouter](https://openrouter.ai/) and streams the answer back. It never runs on its
own — describing a photo costs money, so it waits for the button.

Three horizontal tabs, deliberately not another accordion, because these are three views
of one operation rather than three steps:

- **Prompt** — exactly the text that will be sent, shown before you run anything, plus a
  note about the attached image. Nothing is hidden.
- **Thinking** — the reasoning trace, streamed live, for models that emit one. The tab
  stays disabled until a trace actually arrives, and reasoning is only requested from
  models whose `supported_parameters` advertise it.
- **Description** — the answer, streamed. The view moves here by itself when the model
  stops thinking and starts writing. Word count, token counts and cost land underneath
  when it finishes.

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

The key is stored **in plain text** and is sent only to openrouter.ai — anything with
access to the device or to another script on this origin can read it. The settings dialog
says so. Use a key scoped and budgeted for this.

The model picker lists only vision-capable models — those whose
`architecture.input_modalities` include `image`, 183 of OpenRouter's 345 at the time of
writing — with their input price per million tokens and whether they support reasoning.
A filter box narrows the list. The catalogue is cached under `photomap:models:1:openrouter`
for **24 hours**, with a *Reload model list* button to force a refresh.

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

## Getting GPS data off an iPhone

iOS only hands location data to a web page if you ask it to, per upload:

1. Tap **Choose a photo** and pick **Photo Library**.
2. Tap **Options** at the bottom-left of the picker.
3. Turn **Location** on, then select the photo.

A photo captured through the picker's **Take Photo** option never carries GPS, regardless
of that setting.

## Files

`index.html` is the whole application. Bootstrap 5.3, Bootstrap Icons, Leaflet and exifr
load from CDNs with subresource-integrity hashes; there is no build step.

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
