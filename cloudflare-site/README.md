# Your Cloudflare website

The current design uses a full-width, alternating five-scene background above
a deep-purple page. Scenes: flowing-fabric dance, traffic, grains, water, and
a flock of birds. Silent 1080p Pexels clips crossfade automatically; footage
credits and license links are included. The hero uses the original logo PNG,
has no download button or visible slideshow controls, and retains short copy.
Clips pause offscreen and when the tab is hidden; reduced-motion preferences
are respected. Desktop and 390px mobile browser checks cover full-width layout,
all five Full HD scenes, actual end-of-clip rotation, logo loading, absence of
hero download/controls, and reduced motion. The portrait grains source has less
native horizontal detail than the landscape clips even when exported at 1080p.

The Software section describes recorded analysis, live camera preview/CSV
recording, and manufacturing process studies. Two credited Pexels photographs
are delivered at 1597 x 949, matching the supplied HAND 2 screenshot. They
illustrate applications, not customer deployments or hardware compatibility.

To update an existing Cloudflare project, choose **Create a new deployment**
and upload the new extracted website folder. Do not create another project.

The website is prepared for your own Cloudflare Pages account. No Sites
registration, old Sites identity, application source code, recordings, or
credentials are included in the upload ZIP. It contains the public website,
your approved artwork, your supplied HAND 2 screenshot, the unsigned app candidate,
matching third-party source download, checksums, and legal/privacy documents.

## Upload in your browser

1. Sign in to https://dash.cloudflare.com/ in your own account.
2. Open **Workers & Pages**, then **Create application** and choose the
   **Pages / Direct Upload / Drag and drop** flow. Dashboard wording may vary.
3. Name the project `event-based-studio-alpha-makuza` or another available name.
4. Upload `artifacts/Event-Based-Studio-Cloudflare-Website.zip` from this repo,
   or extract that ZIP and upload its contents as a folder. `index.html` must
   be at the uploaded root. This ZIP is the website, not the Windows app ZIP.
5. Select **Deploy site**. Cloudflare returns your actual `*.pages.dev` address.
   No purchased domain is required. A later custom domain can be attached.

Deployment creates a public website. The page accurately labels this build as
an unsigned release candidate awaiting clean-PC validation, not a stable release.
To restrict review access, configure Cloudflare Access before sharing the URL.

## How the Download buttons work

`dist/downloads.js` reads `dist/downloads/manifest.json`, fetches the listed
16 MiB parts, assembles the original ZIP, checks SHA-256, and starts a browser
download. Both the app and matching Qt/PySide source are provided. Every asset
fits Pages' 25 MiB per-file limit, so this setup needs no R2 bucket. A modern
browser with HTTPS and enough memory for the full ZIP is required. Do not
delete the parts or replace the manifest without regenerating the package.

## Update and verify

From the desktop repo root:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_download_site
.\.venv\Scripts\python.exe -m scripts.prepare_cloudflare_site
node website/check-downloads.mjs cloudflare-site/dist
```

Upload the regenerated ZIP as a new deployment in the same Pages project.
Verify both download buttons, compare SHA-256 against the checksum document,
check the mobile layout, and open the legal/support links at the returned URL.
The Cloudflare-specific headers disable stale manifests and apply a restrictive
content policy. No analytics or external scripts are added by this website.

Optional CLI workflow, from this directory, after installing Node.js:

```powershell
npx.cmd wrangler@4 login
npx.cmd wrangler@4 pages project create event-based-studio-alpha-makuza --production-branch main
npx.cmd wrangler@4 pages deploy dist --project-name event-based-studio-alpha-makuza --branch main
```

The browser handles authentication. Do not paste passwords/API tokens into chat.
This environment has no Cloudflare authentication, so no deployment is claimed
until the account owner completes upload or authorizes a connected CLI session.

Cloudflare reference: https://developers.cloudflare.com/pages/get-started/direct-upload/
