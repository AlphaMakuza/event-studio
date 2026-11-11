"""Package the existing release website for the publisher's Cloudflare Pages account."""
import base64
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "website" / "dist"
    destination = ROOT / "cloudflare-site" / "dist"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    custom_assets = ROOT / "cloudflare-site" / "assets"
    if custom_assets.exists():
        shutil.copytree(custom_assets, destination / "assets", dirs_exist_ok=True)
    # Do not retain superseded footage in the upload after a scene is replaced.
    credit_source = json.loads((source / "assets" / "motion" / "credits.json").read_text(encoding="utf-8"))
    names = {clip["name"] for clip in credit_source["clips"]}
    for file in (destination / "assets" / "motion").iterdir():
        if file.suffix in (".mp4", ".jpg") and file.stem not in names:
            file.unlink()
    for file in (ROOT / "cloudflare-site" / "design").iterdir():
        if file.is_file():
            shutil.copy2(file, destination / file.name)
    # Keep the small event example with its page through dashboard deployments.
    index = destination / "index.html"
    example = destination / "assets" / "industry" / "event-camera-output.jpg"
    embedded = "data:image/jpeg;base64," + base64.b64encode(example.read_bytes()).decode("ascii")
    index.write_text(index.read_text(encoding="utf-8").replace(
        'src="assets/industry/event-camera-output.jpg"', 'src="' + embedded + '"'), encoding="utf-8")
    old_support = "https://event-based-studio-alpha-makuza.luxedance1.chatgpt.site/#support"
    for document in (destination / "documents").glob("*.txt"):
        value = document.read_text(encoding="utf-8")
        value = value.replace(old_support, "See the Support section on this download website.")
        value = value.replace("The website is private staging until release testing is complete.",
                              "This website distributes an unsigned release candidate pending clean-PC testing.")
        document.write_text(value, encoding="utf-8")
    shutil.copy2(ROOT / "cloudflare-site" / "headers.txt", destination / "_headers")
    shutil.copy2(ROOT / "cloudflare-site" / "404.html", destination / "404.html")
    credit_data = json.loads((destination / "assets" / "motion" / "credits.json").read_text(encoding="utf-8"))
    credits = ["Website stock footage", "", "Licensed under the Pexels License: " + credit_data["license"],
               "Accessed: " + credit_data["accessed"], "Edits: " + credit_data["edits"], "",
               "These clips illustrate movement. They are not event-camera recordings or app output.", ""]
    for clip in credit_data["clips"]:
        credits.extend([clip["name"].title() + " — " + clip["creator"], clip["page"], ""])
    (destination / "documents" / "STOCK-FOOTAGE.txt").write_text("\n".join(credits), encoding="utf-8")
    photo_data = json.loads((destination / "assets" / "industry" / "credits.json").read_text(encoding="utf-8"))
    photo_credits = ["Website photographs", "", "Accessed: " + photo_data["accessed"], "",
                     "These photographs illustrate applications, not product installations or endorsements.", ""]
    for photo in photo_data["photos"]:
        photo_credits.extend([photo["name"] + " — " + photo["creator"], photo["page"], ""])
        photo_credits.extend(["License: " + photo["license"], "Edits: " + photo["edits"], ""])
    (destination / "documents" / "PHOTO-CREDITS.txt").write_text("\n".join(photo_credits), encoding="utf-8")
    files = [p for p in destination.rglob("*") if p.is_file()]
    assert len(files) <= 1000, "Cloudflare dashboard upload file limit exceeded"
    assert all(p.stat().st_size <= 25 * 1024 * 1024 for p in files), "Cloudflare's per-asset limit exceeded"
    manifest = json.loads((destination / "downloads" / "manifest.json").read_text(encoding="utf-8"))
    manifest["application"]["label"] = "Windows download"
    (destination / "downloads" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for item in manifest.values():
        digest = hashlib.sha256()
        total = 0
        for part in item["parts"]:
            data = (destination / part).read_bytes()
            digest.update(data)
            total += len(data)
        assert digest.hexdigest() == item["sha256"] and total == item["size"]
    archive = Path(shutil.make_archive(str(ROOT / "artifacts" / "Event-Based-Studio-Cloudflare-Website"), "zip", destination))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"PASS: {len(files)} static files, per-file limits, application/source download integrity.")
    print(f"Cloudflare dashboard upload ZIP: {archive}")


if __name__ == "__main__":
    main()
