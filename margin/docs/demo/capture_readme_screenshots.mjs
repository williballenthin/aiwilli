import { readFile, mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import process from "node:process";
import { basename, dirname, extname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const args = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    args.set(argv[index], argv[index + 1]);
  }
  return {
    outputDir: args.get("--output-dir"),
    playwrightModule: args.get("--playwright-module"),
    review: args.get("--review"),
  };
}

function getContentType(path) {
  const suffix = extname(path);
  if (suffix === ".html") {
    return "text/html; charset=utf-8";
  }
  if (suffix === ".js") {
    return "text/javascript; charset=utf-8";
  }
  if (suffix === ".css") {
    return "text/css; charset=utf-8";
  }
  return "application/octet-stream";
}

function buildState(snapshot) {
  const timestamp = "2026-03-15T12:00:00Z";
  return {
    version: 1,
    snapshotId: snapshot.snapshotId,
    nextSequence: 3,
    reviewedFiles: ["src/app.py"],
    comments: [
      {
        id: "RV-001",
        scope: "repo",
        path: null,
        startLine: null,
        endLine: null,
        excerpt: null,
        title: "Focus on review ergonomics",
        body: "Keep the generated review compact and easy to scan on a laptop screen.",
        createdAt: timestamp,
        updatedAt: timestamp,
      },
      {
        id: "RV-002",
        scope: "range",
        path: "src/app.py",
        startLine: 4,
        endLine: 5,
        excerpt: "def load_items(path: Path) -> list[str]:\n    text = path.read_text()",
        title: "Be explicit about decoding",
        body: "Pass encoding='utf-8' to read_text() so the file-decoding assumption stays visible in the review.",
        createdAt: timestamp,
        updatedAt: timestamp,
      },
    ],
    updatedAt: timestamp,
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options.review || !options.outputDir || !options.playwrightModule) {
    throw new Error("expected --review, --output-dir, and --playwright-module");
  }

  const reviewPath = resolve(options.review);
  const outputDir = resolve(options.outputDir);
  const reviewHtml = await readFile(reviewPath, "utf8");
  const match = reviewHtml.match(/<script id="snapshot-data" type="application\/json">([\s\S]*?)<\/script>/);
  if (!match) {
    throw new Error("failed to find embedded snapshot JSON");
  }
  const snapshot = JSON.parse(match[1]);
  const state = buildState(snapshot);
  const reviewDir = dirname(reviewPath);
  const reviewFileName = basename(reviewPath);

  await mkdir(outputDir, { recursive: true });

  const server = createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
      const requestedPath = pathname === "/" ? `/${reviewFileName}` : pathname;
      const filePath = resolve(reviewDir, `.${requestedPath}`);
      const data = await readFile(filePath);
      response.writeHead(200, { "content-type": getContentType(filePath) });
      response.end(data);
    } catch {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("not found");
    }
  });

  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("failed to resolve server address");
  }
  const reviewUrl = `http://127.0.0.1:${address.port}/${reviewFileName}`;

  const { chromium } = await import(pathToFileURL(resolve(options.playwrightModule)).href);
  const browser = await chromium.launch();
  try {
    const desktopContext = await browser.newContext({
      colorScheme: "light",
      viewport: { width: 1440, height: 960 },
    });
    await desktopContext.addInitScript(
      ({ snapshotId, reviewState }) => {
        window.localStorage.setItem(`margin:${snapshotId}`, JSON.stringify(reviewState));
        window.localStorage.removeItem("margin:presets:v1");
      },
      { reviewState: state, snapshotId: snapshot.snapshotId },
    );
    const desktopPage = await desktopContext.newPage();
    await desktopPage.goto(reviewUrl, { waitUntil: "networkidle" });
    await desktopPage.screenshot({ path: join(outputDir, "margin-desktop.png") });
    await desktopContext.close();

    const mobileContext = await browser.newContext({
      colorScheme: "light",
      hasTouch: true,
      isMobile: true,
      viewport: { width: 390, height: 844 },
    });
    await mobileContext.addInitScript(
      ({ snapshotId, reviewState }) => {
        window.localStorage.setItem(`margin:${snapshotId}`, JSON.stringify(reviewState));
        window.localStorage.removeItem("margin:presets:v1");
      },
      { reviewState: state, snapshotId: snapshot.snapshotId },
    );
    const mobilePage = await mobileContext.newPage();
    await mobilePage.goto(reviewUrl, { waitUntil: "networkidle" });
    await mobilePage.getByRole("button", { name: "Comments" }).click();
    await mobilePage.screenshot({ path: join(outputDir, "margin-mobile.png") });
    await mobileContext.close();
  } finally {
    await browser.close();
    server.close();
  }

  process.stdout.write(`${join(outputDir, "margin-desktop.png")}\n${join(outputDir, "margin-mobile.png")}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
