# Download package updates

The user requires the website upload ZIP to stay current with application changes.
After changing the app, run appropriate tests, rebuild the branded Windows app
with `python -m scripts.build_release --include-approved-assets`, verify it with
`python -m scripts.check_release dist/Event-Based-Studio-2.0.0rc1-windows-x64-preview.zip`
(use the current version's filename if it changes), then run
`python -m scripts.prepare_download_site`,
`python -m scripts.prepare_cloudflare_site`, and
`node website/check-downloads.mjs cloudflare-site/dist`.
Finally run `python -m scripts.verify_workspace_download` to compare all app
modules and assets with the executable and verify the app inside the website ZIP.
Use `.venv/Scripts/python.exe` on Windows. Report the regenerated
`artifacts/Event-Based-Studio-Cloudflare-Website.zip` and distinguish local
packaging from an actual live Cloudflare deployment. Never claim the live
download was updated without verifying deployment.
