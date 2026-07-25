# osm

Photo Map is a single static HTML page that reads the GPS coordinates out of photos you
add from an iPhone (or anywhere else) and plots them on an OpenStreetMap map.

Everything runs in the browser. No photo, thumbnail, or coordinate is ever uploaded —
the page is served as a plain static file and does no network calls beyond map tiles.

## What it does

- accepts photos via a file picker or drag-and-drop, including HEIC/HEIF from iOS
- extracts GPS latitude/longitude, altitude, capture time, and camera model from EXIF
- plots each located photo as a numbered pin on an OpenStreetMap map and fits the view to them
- lists every photo with its thumbnail and coordinates; selecting one flies the map to its pin
- shows full per-photo metadata in a modal, with a deep link to the same spot on openstreetmap.org
- lists the 10 nearest OpenStreetMap entities to a photo — businesses and street furniture
  alike — and lets you pick the one the photo is actually of
- calls out photos that carry no GPS data instead of silently dropping them
- exports the located photos as GeoJSON, including any chosen place
- follows the system light/dark preference, with a manual toggle

## Getting GPS data off an iPhone

iOS only hands location data to a web page if you ask it to, per upload:

1. Tap **Choose photos** and pick **Photo Library**.
2. Tap **Options** at the bottom-left of the picker.
3. Turn **Location** on, then select your photos.

Photos captured through the picker's **Take Photo** option never carry GPS, regardless of
that setting.

## Nearby entities

Select a located photo, then open the **Nearby** tab in the sidebar. It queries the
[Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) for everything mapped
around that photo and lists the 10 nearest. The tab lives in the sidebar rather than in a
dialog so the list and the map are usable at the same time.

Every entity in the list is also drawn on the map as an **amber dot**, distinct from the
photo's own pin. Selection is two-way:

- click a **row** and its point turns green, grows, opens its popup, and the map pans to fit
  it together with the photo;
- click a **point** and the matching row goes active and scrolls into view.

Either way a dashed connector is drawn back to the photo, the photo's row is labelled with
the choice, and the full details appear in a table under the list — category, OSM tag,
kind, distance, coordinates, plus address, opening hours, phone, website and any other
tags the element carries, with every raw tag behind a disclosure. That makes it possible
to browse the results one by one and compare them.

- **Businesses / Objects** filters split shops, restaurants, hotels and offices from
  street furniture such as waste baskets, post boxes, benches, hydrants, and bus stops.
  Filtering re-plots the map so it always matches the list.
- The search starts at 150 m and widens automatically (400 m, 1 km, 2.5 km) when an area
  is too sparse to fill the list; **Wider** steps it out manually.
- A small set of mapping minutiae is excluded so it cannot flood a dense area —
  surveillance cameras, survey points, antennas, utility poles, manholes, street cabinets,
  and street lamps. See `EXCLUDED` in `index.html` to change that.
- Results are fetched once per photo and cached, and only when the tab is opened.

### Which server answered, and how old its data is

Overpass is a free shared service and its public instances refuse requests when busy, so
the page tries a second instance before giving up, and offers a retry rather than failing
silently. That fallback matters for correctness, not just availability: mirrors run their
own database snapshots and can lag badly. At the time of writing `overpass-api.de` was
current to the minute while `overpass.kumi.systems` was **54 days behind** — enough that a
recently mapped feature is missing entirely from one and first in the list on the other.

The page therefore prints which host answered and that host's database timestamp beneath
the results, and flags it in warning colours when the data is more than a week old.

## Files

`index.html` is the whole application. Bootstrap 5.3, Bootstrap Icons, Leaflet, and
exifr load from CDNs with subresource-integrity hashes; there is no build step.

## Deployment

The page is hosted on a [sprite](https://sprites.dev) named `osm`:

```bash
sprite create osm
sprite exec -s osm --file osm/index.html:/home/sprite/site/index.html -- true
sprite exec -s osm -- sprite-services create photomap \
  --cmd /.sprite/bin/python3 \
  --args "-u,-m,http.server,8080,--bind,0.0.0.0,--directory,/home/sprite/site" \
  --http-port 8080
sprite url update --auth public -s osm
```

Registering the server as a sprite service (rather than backgrounding it from `exec`)
is what makes it durable: the sprite proxy routes public traffic to the service's
`--http-port` and starts the service on demand when a request arrives after a sleep.

Redeploy by re-running the `--file` upload; `http.server` reads from disk per request,
so no restart is needed.

To publish an update:

```bash
sprite exec -s osm --file osm/index.html:/home/sprite/site/index.html -- true
curl -sS -o /dev/null -w '%{http_code}\n' https://osm-blpqo.sprites.app/
```
