# osm

Photo Map is a single static HTML page that takes one photo, reads the GPS coordinates
out of its EXIF data, places it on an OpenStreetMap map, and shows what OpenStreetMap has
mapped around it.

Everything runs in the browser. The photo is never uploaded — the page is served as a
plain static file and makes no network calls beyond map tiles and the Overpass API.

## Layout

The page is built mobile first, targeting an iPhone held portrait — an iPhone 17 is
402 × 874 CSS px. The base stylesheet is the phone layout and the desktop split-pane is
the `min-width: 992px` override, not the other way round.

On a phone the page scrolls: phases, then the map, then the details of whatever is
selected. **The detail pane always sits directly under the map**, so picking an entity
from the list scrolls the map up under the sticky navbar and leaves the map and the top
of its details on screen together. On desktop the same relationship holds vertically
inside the right-hand column — map above, details below, sidebar to the left.

Other phone-specific handling: `viewport-fit=cover` plus `env(safe-area-inset-*)` so the
Dynamic Island and home indicator do not overlap content; ~44 px minimum tap targets;
no nested scroll regions (the list scrolls inside itself only on desktop); the scale bar
is hidden where it would collide with the attribution; and marker popups are deliberately
terse, because a tall popup covers most of a 45 dvh map when the full record is already
in the pane below it.

## Phases

The sidebar is a vertical accordion, one phase at a time. Each header carries a status
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

More phases will be added after these.

## Nearby entities

Every entity in the list is also drawn on the map as an **amber dot**, distinct from the
photo's red pin. Selection is two-way:

- click a **row** and its point turns green, grows, opens its popup, and the map pans to
  fit it together with the photo;
- click a **point** and the matching row goes active and scrolls into view.

Either way a dashed connector is drawn back to the photo and the full details appear in
the pane under the map — category, OSM tag, kind, distance, coordinates, plus address,
opening hours, phone, website and any other tags the element carries, with every raw tag
behind a disclosure. That makes it possible to browse the results one by one and compare
them without losing sight of the map.

- **Businesses / Objects** filters split shops, restaurants, hotels and offices from
  street furniture such as waste baskets, post boxes, benches, hydrants and bus stops.
  Filtering re-plots the map so it always matches the list.
- The search starts at 150 m and widens automatically (400 m, 1 km, 2.5 km) when an area
  is too sparse to fill the list; **Wider** steps it out manually.
- A small set of mapping minutiae is excluded so it cannot flood a dense area —
  surveillance cameras, survey points, antennas, utility poles, manholes, street cabinets
  and street lamps. See `EXCLUDED` in `index.html` to change that.
- Overpass is queried once, when the phase is first opened, and the result is cached.
  A spinner runs in the phase header, and the body reports the radius being searched and
  says so when it widens.

### Which server answered, and how old its data is

Overpass is a free shared service and its public instances refuse requests when busy, so
the page tries a second instance before giving up, and offers a retry rather than failing
silently. That fallback matters for correctness, not just availability: mirrors run their
own database snapshots and can lag badly. At the time of writing `overpass-api.de` was
current to the minute while `overpass.kumi.systems` was **54 days behind** — enough that a
recently mapped feature is missing entirely from one and first in the list on the other.

The page therefore prints which host answered and that host's database timestamp beneath
the results, and flags it in warning colours when the data is more than a week old.

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
