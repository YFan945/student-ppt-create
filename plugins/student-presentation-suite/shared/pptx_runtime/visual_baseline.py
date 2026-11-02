"""Encoding-independent visual change detection, not quality acceptance.

RGB fingerprints retain color/local changes; legacy average hashes remain
readable. Differences require inspection and never imply a regression.
"""

from __future__ import annotations

import hashlib
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


def collect_pixels(render_dir: Path) -> dict[str, str]:
    """Encoding-independent RGB fingerprints retain color and local details."""
    result = {}
    for path in sorted(Path(render_dir).glob("*.png")):
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            result[path.name] = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
    return result


def record_baseline(render_dir: Path, baseline_path: Path) -> dict[str, Any]:
    hashes = collect_hashes(render_dir)
    payload = {
        "render_dir": str(render_dir),
        "pages": len(hashes),
        "hashes": hashes,
        "pixels": collect_pixels(render_dir),
        "scope": "change detection only; never visual-quality acceptance",
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
    current_pixels = collect_pixels(render_dir)
    baseline_pixels = baseline.get("pixels", {})

    changed: list[dict[str, Any]] = []
    for name, hash_now in current.items():
        if name not in baseline_hashes:
            changed.append({"page": name, "reason": "new page"})
            continue
        distance = hamming_distance(hash_now, baseline_hashes[name])
        if distance > threshold or (name in baseline_pixels and current_pixels[name] != baseline_pixels[name]):
            changed.append({"page": name, "reason": "pixels changed", "distance": distance})
    missing = sorted(set(baseline_hashes) - set(current))

    return {
        "ok": bool(current),
        "matches": not changed and not missing,
        "review_required": bool(changed or missing),
        "scope": "change detection only; differences may be improvements, not defects",
        "coverage": "RGB pixels and grayscale structure" if baseline_pixels else "legacy grayscale only; record a new baseline for color/detail coverage",
        "pages_current": len(current),
        "pages_baseline": len(baseline_hashes),
        "threshold": threshold,
        "changed": changed,
        "missing": missing,
    }
