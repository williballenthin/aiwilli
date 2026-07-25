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
- calls out photos that carry no GPS data instead of silently dropping them
- exports the located photos as GeoJSON
- follows the system light/dark preference, with a manual toggle

## Getting GPS data off an iPhone

iOS only hands location data to a web page if you ask it to, per upload:

1. Tap **Choose photos** and pick **Photo Library**.
2. Tap **Options** at the bottom-left of the picker.
3. Turn **Location** on, then select your photos.

Photos captured through the picker's **Take Photo** option never carry GPS, regardless of
that setting.

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
