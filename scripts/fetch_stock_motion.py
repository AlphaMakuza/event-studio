"""Prepare website-only Pexels loops from the credited, freely licensed clips."""
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
CLIPS = [
    {"name": "dance", "creator": "cottonbro studio", "page": "https://www.pexels.com/video/woman-dancing-with-fabric-waving-in-wind-10570819/",
     "download": "https://videos.pexels.com/video-files/10570819/10570819-uhd_4096_2160_25fps.mp4"},
    {"name": "traffic", "creator": "Casey Whalen", "page": "https://www.pexels.com/video/cars-moving-along-the-freeway-6733154/",
     "download": "https://videos.pexels.com/video-files/6733154/6733154-hd_1920_1080_30fps.mp4"},
    {"name": "sand", "creator": "ROMAN ODINTSOV", "page": "https://www.pexels.com/video/close-up-footage-of-a-person-pouring-sand-8347918/",
     "download": "https://videos.pexels.com/video-files/8347918/8347918-hd_1080_1920_25fps.mp4"},
    {"name": "water", "creator": "8 K", "page": "https://www.pexels.com/video/slow-motion-of-water-splashing-4170295/",
     "download": "https://videos.pexels.com/video-files/4170295/4170295-hd_1920_1080_24fps.mp4"},
    {"name": "birds", "creator": "CESAR A RAMIREZ VALLEJO TRAPHITHO", "page": "https://www.pexels.com/video/birds-flying-in-sky-13456510/",
     "download": "https://videos.pexels.com/video-files/13456510/13456510-uhd_3840_2160_30fps.mp4"},
]


def main():
    output = ROOT / "website" / "dist" / "assets" / "motion"
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for clip in CLIPS:
        video = output / f"{clip['name']}.mp4"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", clip["download"],
            "-t", "7", "-an", "-vf", "scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(video)], check=True, timeout=180)
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
            "-frames:v", "1", "-q:v", "3", str(output / f"{clip['name']}.jpg")], check=True)
        clip["sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
        print(f"Prepared {clip['name']}: {video.stat().st_size:,} bytes", flush=True)
    (output / "credits.json").write_text(json.dumps({"license": "https://www.pexels.com/license/", "accessed": "2026-11-10",
        "edits": "Up to 7-second silent excerpts, cropped/resized to 1920x1080, H.264 CRF 19 at 30fps; still posters extracted. Portrait source material has limited native horizontal detail.", "clips": CLIPS}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
