// Local mirror of the deployed page: fetches the real index.html from the sprite
// (through the tunnel), rewrites CDN URLs to locally-mirrored byte-identical copies,
// and proxies OSM tile requests out through curl (which can use the egress proxy).
import http from 'node:http';
import fs from 'node:fs';
import { execFile, spawn } from 'node:child_process';
import crypto from 'node:crypto';

// In-memory OpenStreetMap: two elements to edit, plus whatever the page sends.
const osmState = { changesets: [], nextId: 7000, challenge: null, lastToken: null };
const osmElements = (type, id) => {
  // The pavilion the suites edit. A way is included so the test can prove the
  // <nd> children survive a tag-only edit.
  if (type === 'node' && id === '14040292373') {
    const moved = mode.osmMoved ? '<tag k="operator" v="Someone Else"/>' : '';
    return `<node id="14040292373" version="3" lat="53.9896194" lon="-1.5514974" ` +
      `changeset="1" timestamp="2026-07-01T00:00:00Z" user="prior" uid="9">` +
      `<tag k="leisure" v="sports_centre"/><tag k="name" v="Valley Gardens Games Paviliom"/>` +
      `<tag k="opening_hours" v="Mo-Fr off; Sa-Su,PH 10:00-17:00"/>` +
      `<tag k="sport" v="table_tennis;tennis;disc_golf"/>${moved}</node>`;
  }
  if (type === 'way' && id === '900001') {
    return `<way id="900001" version="5" changeset="1" timestamp="2026-07-01T00:00:00Z">` +
      `<nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/>` +
      `<tag k="building" v="yes"/></way>`;
  }
  return null;
};


/** The fixtures are written as XML; the batch routes answer in JSON. */
const xmlElementToJson = (type, id) => {
  const xml = osmElements(type, id);
  const attr = n => (xml.match(new RegExp(`${n}="([^"]*)"`)) || [])[1];
  const tags = {};
  for (const m of xml.matchAll(/<tag k="([^"]*)" v="([^"]*)"\/>/g)) tags[m[1]] = m[2];
  const el = { type, id: Number(id), version: Number(attr('version')), tags };
  if (type === 'node') { el.lat = Number(attr('lat')); el.lon = Number(attr('lon')); }
  if (type === 'way') el.nodes = [...xml.matchAll(/<nd ref="(\d+)"\/>/g)].map(m => Number(m[1]));
  return el;
};

const SPRITE = process.env.SPRITE_URL || 'http://127.0.0.1:8080/';
/* One mirror per suite, so suites can run at once without fighting over the
   scenario or over the in-memory OpenStreetMap. The OSM origins have to be
   rewritten to absolute URLs — the page builds its authorize URL against them —
   so the port has to be baked into the rewrite table too. */
const PORT = Number(process.env.PORT || 8099);
const SELF = `http://127.0.0.1:${PORT}`;

const REWRITES = [
  ['https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css', '/vendor/bootstrap.min.css'],
  ['https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css', '/vendor/bootstrap-icons.min.css'],
  ['https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', '/vendor/leaflet.css'],
  ['https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js', '/vendor/bootstrap.bundle.min.js'],
  ['https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', '/vendor/leaflet.js'],
  ['https://cdn.jsdelivr.net/npm/exifr@7.1.3/dist/full.umd.js', '/vendor/exifr.js'],
  // Lazily injected from JS, but the URL is a literal in the inline script, so
  // the same blanket rewrite catches it. The local copy is byte-identical, so
  // the SRI the page sets on the element still validates.
  ['https://cdn.jsdelivr.net/npm/opening_hours@3.14.0/build/opening_hours.js', '/vendor/opening_hours.js'],
  ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '/osmtile/{z}/{x}/{y}.png'],
  ['https://overpass-api.de/api/interpreter', '/overpass/primary'],
  ['https://overpass.kumi.systems/api/interpreter', '/overpass/fallback'],
  ['https://cdn.jsdelivr.net/npm/@openstreetmap/id-tagging-schema@7.0.1/dist', '/idschema'],
  ['https://taginfo.openstreetmap.org/api/4', '/taginfo'],
  ['https://openrouter.ai/api/v1', '/openrouter'],
  // Both OSM servers are stood in for locally: real OAuth needs a human at a
  // login page, and a real upload would write to a public database. These have
  // to stay absolute — the page builds the authorize URL with `new URL(path,
  // server)`, and a bare path is not a usable base.
  ['https://master.apis.dev.openstreetmap.org', `${SELF}/osmdev`],
  ['https://www.openstreetmap.org', `${SELF}/osmlive`],
  ['https://api.openstreetmap.org', `${SELF}/osmlive`],
];

const rawCurl = (url, binary, extra = []) => new Promise((res, rej) =>
  execFile('curl', ['-sSL', '-m', '30', ...extra, url],
    { encoding: binary ? 'buffer' : 'utf8', maxBuffer: 1 << 26 },
    (e, out) => e ? rej(e) : res(out)));

/* Every upstream this mirror proxies — the iD schema, taginfo, Overpass, the
   OSM API, map tiles — is read-only and, for the fixtures the suites use,
   unchanging. Fetching them live made the same drive take anywhere from 11 to
   39 seconds depending on how busy taginfo was, and made assertions fail
   whenever somebody edited Harrogate. Both problems go away by recording each
   response once and replaying it.

   RECORD=1 re-fetches and overwrites, which is how the fixtures get refreshed
   deliberately rather than drifting under the suite. */
const CACHE_DIR = new URL('./.upstream/', import.meta.url).pathname;
fs.mkdirSync(CACHE_DIR, { recursive: true });
const cacheFile = (url, binary) =>
  CACHE_DIR + crypto.createHash('sha1').update(url).digest('hex') + (binary ? '.bin' : '.txt');

let recorded = 0, replayed = 0;
async function curl(url, binary, extra = []) {
  const file = cacheFile(url, binary);
  if (!process.env.RECORD && fs.existsSync(file)) {
    replayed++;
    return binary ? fs.readFileSync(file) : fs.readFileSync(file, 'utf8');
  }
  const out = await rawCurl(url, binary, extra);
  fs.writeFileSync(file, out);
  recorded++;
  return out;
}

/* Which scenario the mirror is playing. Suites used to pick this with
   environment variables and a restart, at three seconds a time and no way to
   run two suites at once; now they POST to /_mode. The environment still
   supplies the defaults so a one-off `OH_MODE=dirty ./restart-mirror.sh` for
   debugging by hand keeps working. */
const mode = {
  oh: process.env.OH_MODE || 'clean',
  badTags: !!process.env.BAD_TAGS,
  vocab: !!process.env.VOCAB,
  osmMoved: !!process.env.OSM_MOVED,
  osmFail: process.env.OSM_FAIL || '',
  osmDeny: !!process.env.OSM_DENY,
  osmMapFail: !!process.env.OSM_MAP_FAIL,
  osmCloseFail: !!process.env.OSM_CLOSE_FAIL,
};
const DEFAULT_MODE = { ...mode };

const MIME = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png' };

http.createServer(async (req, res) => {
  try {
    const path = req.url.split('?')[0];

    /* Scenario control. A suite posts the switches it wants and gets the whole
       resulting mode back; posting nothing resets to the defaults. Also resets
       the in-memory OSM so one suite's changesets cannot leak into another's. */
    if (path === '/_mode') {
      if (req.method === 'POST') {
        const body = await new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b)); });
        const want = body ? JSON.parse(body) : {};
        Object.assign(mode, DEFAULT_MODE, want);
        if (want.reset !== false) {
          osmState.changesets.length = 0;
          osmState.nextId = 7000;
        }
      }
      return res.writeHead(200, { 'content-type': 'application/json' })
        .end(JSON.stringify({ mode, upstream: { recorded, replayed } }));
    }

    if (path === '/' || path === '/index.html') {
      // rawCurl, never curl: the page under test is the one thing here that
      // changes on every deploy, and serving it from the upstream cache means
      // testing the previous build.
      let html = await rawCurl(SPRITE);
      for (const [from, to] of REWRITES) html = html.split(from).join(to);
      // Local copies are byte-identical to the CDN originals (hashes verified separately),
      // but same-origin paths can't carry the CDN SRI attributes.
      html = html.replace(/\s+integrity="[^"]*"/g, '').replace(/\s+crossorigin="anonymous"/g, '');
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end(html);
      return;
    }

    // Forward the page's Overpass POST out through curl (which can use the egress proxy).
    if (path.startsWith('/overpass/')) {
      const host = path.endsWith('/fallback') ? 'overpass.kumi.systems' : 'overpass-api.de';
      const body = await new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b)); });
      // Overpass sheds load constantly; retry a few times so the test isn't flaky.
      // Keyed on the query, not just the host: the page asks two different
      // things of Overpass and they must not share a cache entry.
      const key = `overpass:${host}:${crypto.createHash('sha1').update(body).digest('hex')}`;
      const file = cacheFile(key, false);
      let out = '';
      if (!process.env.RECORD && fs.existsSync(file)) {
        out = fs.readFileSync(file, 'utf8');
        replayed++;
      } else {
        for (let attempt = 0; attempt < 4; attempt++) {
          out = await new Promise((resolve, reject) =>
            execFile('curl', ['-sS', '-m', '90', '-X', 'POST',
              '-A', 'photo-map-dev/1.0 (local verification harness)',
              '--data-binary', body, `https://${host}/api/interpreter`],
              { encoding: 'utf8', maxBuffer: 1 << 26 }, (e, o) => e ? reject(e) : resolve(o)));
          if (out.trimStart().startsWith('{')) break;
          console.log(`overpass ${host} attempt ${attempt + 1} busy, retrying`);
          await new Promise(r => setTimeout(r, 3000 * (attempt + 1)));
        }
        if (out.trimStart().startsWith('{')) { fs.writeFileSync(file, out); recorded++; }
      }
      const ok = out.trimStart().startsWith('{');
      console.log(`overpass ${host} -> ${ok ? 'json ' + out.length + 'B' : 'NON-JSON: ' + out.slice(0, 80)}`);
      res.writeHead(ok ? 200 : 504, { 'content-type': ok ? 'application/json' : 'text/plain' }).end(out);
      return;
    }

    // OpenRouter's model list is public, so that one is a real passthrough.
    if (path === '/openrouter/models') {
      const body = await curl('https://openrouter.ai/api/v1/models');
      const ok = body.trimStart().startsWith('{');
      console.log(`openrouter/models -> ${ok ? body.length + 'B' : 'NON-JSON'}`);
      res.writeHead(ok ? 200 : 502, { 'content-type': 'application/json' }).end(body);
      return;
    }

    // With REAL_OPENROUTER=1 the chat completion is proxied to the genuine endpoint,
    // streaming SSE straight through as curl emits it. The client's own Authorization
    // header is forwarded, so the real auth path is exercised too.
    if (path === '/openrouter/chat/completions' && process.env.REAL_OPENROUTER === '1') {
      const raw = await new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b)); });
      const auth = req.headers.authorization || '';
      console.log(`openrouter/chat REAL passthrough, ${raw.length}B body, auth ${auth ? 'present' : 'MISSING'}`);
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
      const cp = spawn('curl', ['-sS', '-N', '-X', 'POST',
        '-H', 'Content-Type: application/json',
        '-H', `Authorization: ${auth}`,
        '-H', `HTTP-Referer: ${SELF}`,
        '-H', 'X-Title: Photo Map',
        '--data-binary', '@-', 'https://openrouter.ai/api/v1/chat/completions']);
      cp.stdin.end(raw);
      cp.stdout.pipe(res);
      cp.stderr.on('data', d => console.log('curl stderr:', String(d).slice(0, 200)));
      cp.on('close', () => res.end());
      return;
    }

    // The chat completion is SIMULATED. There is no API key in this environment and
    // the browser cannot reach openrouter.ai anyway, so this stands in for the real
    // endpoint to exercise the client: SSE framing, reasoning deltas, content deltas,
    // usage and [DONE]. It echoes back what it was actually sent so the test can
    // assert the prompt and the image really made it into the request.
    if (path === '/openrouter/chat/completions') {
      const raw = await new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b)); });
      const auth = req.headers.authorization || '';
      let parsed = null;
      try { parsed = JSON.parse(raw); } catch { /* handled below */ }

      if (!/^Bearer .+/.test(auth)) {
        res.writeHead(401, { 'content-type': 'application/json' })
           .end(JSON.stringify({ error: { message: 'No auth credentials found' } }));
        return;
      }
      const content = parsed?.messages?.[0]?.content || [];

      // The tagging request (step 6) is text-only and asks for a JSON schema.
      if (typeof content === 'string' && parsed?.response_format) {
        const prompt = content;
        console.log(`openrouter/chat TAGGING model=${parsed.model} prompt=${prompt.length}B ` +
                    `schema=${parsed.response_format?.json_schema?.name}`);
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
        const send = o => res.write(`data: ${JSON.stringify(o)}\n\n`);
        // OH_MODE lets a suite pick which opening_hours shape comes back:
        // clean by default, 'dirty' for a value that parses with warnings,
        // 'broken' for one that does not parse at all.
        const HOURS = { clean: 'Sa-Su,PH 10:00-17:30',
                        dirty: 'Weekends 10.00am-5.30pm',
                        broken: 'open at weekends ten til half five' };
        // BAD_TAGS makes the model return exactly the things the community has
        // blocked mappers over, so the output filter has something to catch.
        const bad = mode.badTags ? [
          { key: 'name:de', value: 'Talgarten-Spielhaus',
            evidence: 'the board is headed Valley Gardens', confidence: 'medium' },
          { key: 'wikidata', value: 'Q42', evidence: 'a well-known park', confidence: 'low' },
          { key: 'description', value: 'A charming pavilion in a lovely park.',
            evidence: 'blue and white board', confidence: 'medium' },
          { key: 'access', value: 'customer',
            evidence: 'sign says customers only', confidence: 'high' },
          { key: 'website', value: 'https://www.valleygardens-harrogate.co.uk',
            evidence: 'the board carries the North Yorkshire Council logo', confidence: 'medium' },
          { key: 'wheelchair', value: 'probably',
            evidence: 'a ramp at the door', confidence: 'low' },
          // A model that has run away with itself, on a key that is otherwise
          // perfectly allowed — so the only thing wrong is the length.
          { key: 'operator:short', value: 'A'.repeat(300),
            evidence: 'the board', confidence: 'low' },
          // Emoji, to prove the count is codepoints and not UTF-16 units: 200
          // of these are 400 units and would fail a naive .length test while
          // being perfectly legal.
          { key: 'inscription', value: '🌳'.repeat(200),
            evidence: 'carved into the bench', confidence: 'low' },
        ] : [];
        // VOCAB makes the model reach outside the reference editor's value list
        // in three different ways, so the provenance badges have all three to
        // report: one value in wide use that iD simply does not offer, one used
        // by a handful of objects, and one nothing anywhere uses.
        const vocab = mode.vocab ? [
          { key: 'sport', value: 'padel;kubb', evidence: 'a padel court and a kubb lawn',
            confidence: 'high' },
          { key: 'cuisine', value: 'nordic_fusion', evidence: 'the cafe board says Nordic fusion',
            confidence: 'medium' },
          { key: 'wheelchair', value: 'limited', evidence: 'a ramp, but a narrow doorway',
            confidence: 'medium' },
        ] : [];
        const facts = { facts: [...bad, ...vocab,
          { key: 'opening_hours', value: HOURS[mode.oh] || HOURS.clean,
            evidence: 'Weekends, School holidays and Bank Holidays 10.00am - 5.30pm',
            confidence: 'high' },
          { key: 'operator', value: 'North Yorkshire Council',
            evidence: 'carries the North Yorkshire Council logo', confidence: 'high' },
          { key: 'sport', value: 'table_tennis;tennis;disc_golf',
            evidence: 'lists Tennis, Crazy Golf, Disc Golf and Table Tennis', confidence: 'high' },
          { key: 'website', value: 'http://www.harrogate.gov.uk/games-in-parks',
            evidence: 'www.club… printed on the board', confidence: 'low' },
        ] };
        const think = ['Comparing the description against the schema. ',
                       'The hours line is explicit. ', 'The operator logo is stated. '];
        const body = JSON.stringify(facts, null, 2).match(/[\s\S]{1,24}/g);
        let i = 0;
        const tick = setInterval(() => {
          if (i < think.length && parsed.reasoning) send({ choices: [{ delta: { reasoning: think[i] } }] });
          else if (i - (parsed.reasoning ? think.length : 0) < body.length) {
            send({ choices: [{ delta: { content: body[i - (parsed.reasoning ? think.length : 0)] } }] });
          } else {
            clearInterval(tick);
            send({ choices: [{ delta: {} }], usage: { prompt_tokens: 2100, completion_tokens: 180, cost: 0.0009 } });
            res.write('data: [DONE]\n\n');
            res.end();
            return;
          }
          i++;
        }, 8);
        return;
      }

      const promptPart = content.find?.(c => c.type === 'text')?.text || '';
      const imagePart = content.find?.(c => c.type === 'image_url')?.image_url?.url || '';
      console.log(`openrouter/chat model=${parsed?.model} stream=${parsed?.stream} ` +
                  `reasoning=${!!parsed?.reasoning} prompt=${promptPart.length}B image=${imagePart.length}B`);

      res.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      });
      const send = o => res.write(`data: ${JSON.stringify(o)}\n\n`);
      const delta = d => send({ choices: [{ delta: d }] });

      const think = ['Looking at the sign. ', 'Reading the small print. ', 'Checking the header. '];
      const words = (
        `[simulated] Received a ${promptPart.length}-character prompt and a ` +
        `${Math.round(imagePart.length / 1024)} kB image (${imagePart.slice(0, 23)}…). ` +
        `The photograph shows a white rendered wall carrying two notices. ` +
        `The nearer one is a silver snap frame headed "Opening Hours" reading ` +
        `"Weekends, School holidays and Bank Holidays 10.00am - 5.30pm". ` +
        `To its right a larger blue and white board lists Tennis, Crazy Golf, ` +
        `Disc Golf and Table Tennis, and carries the North Yorkshire Council logo. ` +
        `A dark glossy door occupies the left of the frame.`
      ).split(/(?<= )/);

      res.write(': OPENROUTER PROCESSING\n\n');      // keep-alive comment the client must ignore
      let i = 0;
      const tick = setInterval(() => {
        if (i < think.length && parsed?.reasoning) delta({ reasoning: think[i] });
        else if (i - (parsed?.reasoning ? think.length : 0) < words.length) {
          delta({ content: words[i - (parsed?.reasoning ? think.length : 0)] });
        } else {
          clearInterval(tick);
          send({ choices: [{ delta: {} }], usage: { prompt_tokens: 1234, completion_tokens: 210, cost: 0.0031 } });
          res.write('data: [DONE]\n\n');
          res.end();
          return;
        }
        i++;
      }, 12);
      return;
    }

    // The iD tagging schema (jsdelivr) and taginfo, fetched out through curl.
    for (const [prefix, upstream] of [
      ['/idschema/', 'https://cdn.jsdelivr.net/npm/@openstreetmap/id-tagging-schema@7.0.1/dist/'],
      ['/taginfo/', 'https://taginfo.openstreetmap.org/api/4/'],
    ]) {
      if (!path.startsWith(prefix)) continue;
      const target = upstream + req.url.split('?')[0].slice(prefix.length) +
        (req.url.includes('?') ? '?' + req.url.split('?')[1] : '');
      const body = await curl(target);
      const ok = /^\s*[[{]/.test(body);
      console.log(`${prefix} ${target.slice(0, 90)} -> ${ok ? body.length + 'B' : 'NON-JSON'}`);
      res.writeHead(ok ? 200 : 502, { 'content-type': 'application/json' }).end(body);
      return;
    }

    if (path.startsWith('/osmtile/')) {
      const png = await curl('https://tile.openstreetmap.org/' + path.slice('/osmtile/'.length), true);
      res.writeHead(200, { 'content-type': 'image/png' }).end(png);
      return;
    }


    /* ---- stand-in for an OpenStreetMap server ----------------------------
       The real thing needs a human at a login page and writes to a public
       database, so both are faked here: the authorize endpoint bounces
       straight back with a code, and the API keeps its elements in memory.
       OSM_* env vars let a suite pick the failure it wants to exercise. */
    if (path.startsWith('/osmdev/') || path.startsWith('/osmlive/')) {
      const which = path.startsWith('/osmdev/') ? 'dev' : 'live';
      const rest = path.slice(which === 'dev' ? '/osmdev'.length : '/osmlive'.length);
      const read = () => new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b)); });
      const json = (code, o) =>
        res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(o));
      const xml = (code, t) =>
        res.writeHead(code, { 'content-type': 'text/xml' }).end(t);

      // The authorize page: no login, just redirect back with a code.
      if (rest === '/oauth2/authorize') {
        const q = new URLSearchParams(req.url.split('?')[1] || '');
        if (mode.osmDeny) {
          res.writeHead(302, { location: `${q.get('redirect_uri')}?error=access_denied` }).end();
          return;
        }
        osmState.challenge = q.get('code_challenge');
        osmState.method = q.get('code_challenge_method');
        osmState.clientId = q.get('client_id');
        osmState.scope = q.get('scope');
        osmState.redirect = q.get('redirect_uri');
        console.log(`osm/authorize ${which} client=${osmState.clientId} scope=${osmState.scope} ` +
                    `challenge=${osmState.method}`);
        res.writeHead(302, { location: `${q.get('redirect_uri')}?code=THE-CODE&state=${q.get('state')}` }).end();
        return;
      }

      if (rest === '/oauth2/token') {
        const form = new URLSearchParams(await read());
        const verifier = form.get('code_verifier') || '';
        const expected = crypto.createHash('sha256').update(verifier).digest('base64')
          .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        console.log(`osm/token ${which} grant=${form.get('grant_type')} pkce_ok=${expected === osmState.challenge}`);
        osmState.lastToken = Object.fromEntries(form);
        if (form.get('code') !== 'THE-CODE') return json(400, { error: 'invalid_grant' });
        if (!verifier || expected !== osmState.challenge) return json(400, { error: 'invalid_grant',
          error_description: 'PKCE verifier does not match the challenge' });
        return json(200, { access_token: `tok-${which}`, token_type: 'Bearer', scope: osmState.scope });
      }

      // Real OSM serves element reads to anyone; only writes and /user/details
      // need a token. The XML preview relies on that.
      const auth = req.headers.authorization || '';
      const needsAuth = req.method !== 'GET' || rest === '/api/0.6/user/details';
      if (rest.startsWith('/api/') && needsAuth && auth !== `Bearer tok-${which}`) {
        return xml(401, 'Couldn\'t authenticate you');
      }

      if (rest === '/api/0.6/user/details') {
        return xml(200, `<osm><user id="42" display_name="test_mapper"/></osm>`);
      }

      /* The bbox download the nearby step now runs on. Proxied to the real API
         so the suites keep meeting real Harrogate, with one substitution: the
         pavilion's name is forced back to the fixture spelling, so the list row
         and the tags the element routes below serve tell the same story. Real
         OSM corrected that typo mid-project. */
      if (rest === '/api/0.6/map.json' && req.method === 'GET') {
        if (mode.osmMapFail) return xml(400, 'You requested too many nodes (limit is 50000)');
        const q = req.url.split('?')[1] || '';
        const body = await curl(`https://api.openstreetmap.org/api/0.6/map.json?${q}`);
        const ok = /^\s*\{/.test(body);
        console.log(`osm/map ${q.slice(0, 60)} -> ${ok ? body.length + 'B' : 'NON-JSON'}`);
        return res.writeHead(ok ? 200 : 502, { 'content-type': 'application/json' })
          .end(body.split('Valley Gardens Games Pavilion').join('Valley Gardens Games Paviliom'));
      }

      /* Batch element reads, used to fill in tags for what is on screen. The
         two fixture elements answer from memory so a suite's expectations hold;
         anything else is proxied. */
      let batch = rest.match(/^\/api\/0\.6\/(node|way|relation)s\.json$/);
      if (batch && req.method === 'GET') {
        const type = batch[1];
        const ids = (new URLSearchParams(req.url.split('?')[1] || '').get(`${type}s`) || '')
          .split(',').filter(Boolean);
        const known = [], unknown = [];
        for (const id of ids) (osmElements(type, id) ? known : unknown).push(id);
        const out = known.map(id => xmlElementToJson(type, id));
        if (unknown.length) {
          const body = await curl(`https://api.openstreetmap.org/api/0.6/${type}s.json`
                                  + `?${type}s=${unknown.join(',')}`);
          try { out.push(...(JSON.parse(body).elements || [])); }
          catch { /* a deleted id 404s the batch; the page falls back to one each */ }
        }
        console.log(`osm/${type}s ${ids.length} asked -> ${out.length} served`);
        return json(200, { version: '0.6', elements: out });
      }

      // GET an element. OSM_MOVED makes one of them look edited by someone else.
      let m = rest.match(/^\/api\/0\.6\/(node|way|relation)\/(\d+)$/);
      if (m && req.method === 'GET') {
        const [, type, id] = m;
        const el = osmElements(type, id);
        if (!el) return xml(404, 'not found');
        return xml(200, `<osm version="0.6">${el}</osm>`);
      }

      if (rest === '/api/0.6/changeset/create' && req.method === 'PUT') {
        const body = await read();
        osmState.changesets.push({ id: ++osmState.nextId, body, uploads: [], closed: false });
        console.log(`osm/changeset create -> ${osmState.nextId}`);
        if (mode.osmFail === 'create') return xml(500, 'changeset create exploded');
        return res.writeHead(200, { 'content-type': 'text/plain' }).end(String(osmState.nextId));
      }

      m = rest.match(/^\/api\/0\.6\/changeset\/(\d+)\/upload$/);
      if (m && req.method === 'POST') {
        const body = await read();
        const cs = osmState.changesets.find(c => c.id === Number(m[1]));
        if (cs) cs.uploads.push(body);
        console.log(`osm/changeset ${m[1]} upload ${body.length}B`);
        if (mode.osmFail === 'upload') return xml(409, 'Version mismatch: Provided 1, server had 2');
        return xml(200, '<diffResult version="0.6"/>');
      }

      m = rest.match(/^\/api\/0\.6\/changeset\/(\d+)\/close$/);
      if (m && req.method === 'PUT') {
        console.log(`osm/changeset ${m[1]} close${mode.osmCloseFail ? ' (refused)' : ''}`);
        // Refusing a close is how the dangling-changeset path gets exercised:
        // the page can only remember one it could not tidy up.
        if (mode.osmCloseFail) return xml(500, 'close exploded');
        const cs = osmState.changesets.find(c => c.id === Number(m[1]));
        if (cs) cs.closed = true;
        return res.writeHead(200).end('');
      }

      // Reading a changeset back, which is how the page tells whether one it
      // remembers is still open or has since closed itself.
      m = rest.match(/^\/api\/0\.6\/changeset\/(\d+)$/);
      if (m && req.method === 'GET') {
        const cs = osmState.changesets.find(c => c.id === Number(m[1]));
        if (!cs) return xml(404, 'not found');
        return xml(200, `<osm version="0.6"><changeset id="${cs.id}" user="test_mapper" uid="42" `
          + `open="${cs.closed ? 'false' : 'true'}"/></osm>`);
      }

      // A suite reads back what the page actually sent.
      if (rest === '/_state') return json(200, osmState);

      console.log('osm 404 ->', req.method, rest);
      return xml(404, 'not found');
    }

    /* The CDN libraries, fetched through the same recording cache as everything
       else rather than checked in: they are two megabytes of somebody else's
       build output, and the first run records them once. The rewrite table
       above is the list of what may be asked for, so an unknown path is a
       mistake rather than something to go and fetch. */
    /* Bootstrap Icons' stylesheet asks for its font files by relative path, so
       they arrive as /vendor/fonts/*. Getting this wrong is quiet and costly:
       every icon falls back to a "¿" and every screenshot looks broken in a way
       that has nothing to do with the page. */
    if (path.startsWith('/vendor/fonts/')) {
      const body = await curl('https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font'
        + path.slice('/vendor'.length), true);
      return res.writeHead(200, { 'content-type': path.endsWith('.woff2') ? 'font/woff2' : 'font/woff' })
        .end(body);
    }

    if (path.startsWith('/vendor/')) {
      const upstream = REWRITES.find(([, to]) => to === path.replace(/\?.*$/, ''))?.[0];
      if (!upstream) { res.writeHead(404).end('not a vendored file'); return; }
      const ext = path.slice(path.lastIndexOf('.'));
      const binary = ext === '.woff2';
      const body = await curl(upstream, binary);
      res.writeHead(200, { 'content-type': MIME[ext] || 'application/octet-stream' }).end(body);
      return;
    }

    console.log('404 ->', path); res.writeHead(404).end('not found');
  } catch (e) {
    res.writeHead(502).end(String(e));
  }
}).listen(PORT, () => console.log(`mirror on ${SELF}/`));
