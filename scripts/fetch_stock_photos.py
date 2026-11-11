"""Download credited industry photographs at the website screenshot's dimensions."""
import hashlib
import json
from pathlib import Path
import urllib.request

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = [
    {'name': 'event-camera-output', 'creator': 'TimoStoffregen', 'page': 'https://commons.wikimedia.org/wiki/File:Event_camera_comparison.jpg', 'license': 'https://creativecommons.org/licenses/by-sa/4.0/', 'download': 'https://upload.wikimedia.org/wikipedia/commons/2/26/Event_camera_comparison.jpg', 'edits': 'None. Original 1500 x 568 image displayed without cropping.', 'sha256': '96db91f75473277a6078edd438b4dc83aa29942a516f817f0df8d251547885dd'},
    {"name": "manufacturing", "id": "18631424", "creator": "Vladimir Srajber",
     "page": "https://www.pexels.com/photo/bottles-of-water-in-factory-18631424/",
     "license": "https://www.pexels.com/license/",
     "edits": "Pexels image service crop to 1597 x 949."},
]


def main():
    output = ROOT / "cloudflare-site" / "assets" / "industry"
    output.mkdir(parents=True, exist_ok=True)
    for photo in PHOTOS:
        if "id" in photo:
            photo["download"] = f"https://images.pexels.com/photos/{photo['id']}/pexels-photo-{photo['id']}.jpeg?auto=compress&cs=tinysrgb&w=1597&h=949&fit=crop&q=90"
        destination = output / f"{photo['name']}.jpg"
        request = urllib.request.Request(photo["download"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        destination.write_bytes(data)
        expected = (1500, 568) if photo["name"] == "event-camera-output" else (1597, 949)
        with Image.open(destination) as image:
            assert image.size == expected, f"Unexpected photo dimensions: {image.size}"
        photo["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
        print(f"Prepared {photo['name']}: {expected}", flush=True)
    (output / "credits.json").write_text(json.dumps({"accessed": "2026-11-10", "photos": PHOTOS}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
