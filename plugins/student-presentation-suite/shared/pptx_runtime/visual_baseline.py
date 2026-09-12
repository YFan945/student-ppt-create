"""Perceptual-hash visual baseline for rendered decks.

Renders are reduced to 64-bit average hashes. ``record`` stores the baseline;
``compare`` flags pages whose hash distance exceeds a threshold, giving the
deck pipeline a reproducible visual-regression defence: any unplanned pixel
change (palette drift, layout shift, missing panel) shows up as a changed
page, while re-encodings that keep the picture identical pass silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

HASH_SIZE = 8  # 8x8 = 64-bit hash
MAX_DISTANCE_BITS = 64


def average_hash(image_path: Path) -> str:
    """16-hex-char average hash of an image."""
    with Image.open(image_path) as img:
        gray = img.convert("L").resize((HASH_SIZE, HASH_SIZE))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= mean else "0" for p in pixels)
    return f"{int(bits, 2):016x}"


def hamming_distance(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def collect_hashes(render_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for png in sorted(Path(render_dir).glob("*.png")):
        hashes[png.name] = average_hash(png)
    return hashes


def record_baseline(render_dir: Path, baseline_path: Path) -> dict[str, Any]:
    hashes = collect_hashes(render_dir)
    payload = {
        "render_dir": str(render_dir),
        "pages": len(hashes),
        "hashes": hashes,
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def compare_baseline(
    render_dir: Path, baseline_path: Path, threshold: int = 6
) -> dict[str, Any]:
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    baseline_hashes: dict[str, str] = baseline.get("hashes", {})
    current = collect_hashes(render_dir)

    changed: list[dict[str, Any]] = []
    for name, hash_now in current.items():
        if name not in baseline_hashes:
            changed.append({"page": name, "reason": "new page"})
            continue
        distance = hamming_distance(hash_now, baseline_hashes[name])
        if distance > threshold:
            changed.append({"page": name, "reason": "pixels changed", "distance": distance})
    missing = sorted(set(baseline_hashes) - set(current))

    return {
        "ok": not changed and not missing,
        "pages_current": len(current),
        "pages_baseline": len(baseline_hashes),
        "threshold": threshold,
        "changed": changed,
        "missing": missing,
    }
