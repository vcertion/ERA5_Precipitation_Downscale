#!/usr/bin/env python3
"""Download WorldClim v2.1 and CHELSA v2.1 monthly precipitation baselines.

The script only downloads source files. It does not crop, reproject, or
resample them; those operations should be done after checking the downloaded
files and their metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


WORLDCLIM_URL = (
    "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/"
    "wc2.1_{resolution}_prec.zip"
)

# CHELSA's public object-storage layout. Use --chelsa-base-url if the provider
# changes the path. The template must contain {month}, formatted as 01..12.
CHELSA_URL = (
    "https://os.zhdk.cloud.switch.ch/chelsav2/GLOBAL/monthly/pr/"
    "CHELSA_pr_1981-2010_{month}.tif"
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, retries: int = 3) -> dict:
    """Download one URL with resume support and return a manifest record."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")

    for attempt in range(1, retries + 1):
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "climate-baseline-downloader/1.0"}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                status = getattr(response, "status", response.getcode())
                # A server may ignore Range and return the whole file.
                append = existing > 0 and status == 206
                if not append:
                    existing = 0
                mode = "ab" if append else "wb"
                with partial.open(mode) as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)

            partial.replace(destination)
            return {
                "url": url,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            }
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Download failed after {retries} attempts: {url}\n{exc}") from exc
            wait_seconds = 2 ** (attempt - 1)
            print(f"Download attempt {attempt} failed; retrying in {wait_seconds}s: {exc}", file=sys.stderr)
            time.sleep(wait_seconds)

    raise AssertionError("unreachable")


def check_zip(path: Path) -> None:
    """Check the central directory and each member's CRC."""
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"Corrupt ZIP member: {bad_member}")


def parse_months(value: str) -> list[int]:
    months: list[int] = []
    for item in value.split(","):
        month = int(item.strip())
        if month < 1 or month > 12:
            raise argparse.ArgumentTypeError("months must contain integers from 1 to 12")
        if month not in months:
            months.append(month)
    return months


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("worldclim", "chelsa", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("data/climate_baselines"))
    parser.add_argument(
        "--worldclim-resolution",
        choices=("30s", "2.5m", "5m", "10m"),
        default="30s",
        help="WorldClim grid. 30s is approximately 1 km at the equator.",
    )
    parser.add_argument("--months", type=parse_months, default=list(range(1, 13)))
    parser.add_argument(
        "--chelsa-url-template",
        default=CHELSA_URL,
        help="CHELSA URL template containing {month}; use this if the official host changes.",
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--list-only", action="store_true", help="Print URLs without downloading files.")
    args = parser.parse_args()

    if args.retries < 1:
        parser.error("--retries must be at least 1")

    records: list[dict] = []
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.dataset in ("worldclim", "both"):
        url = WORLDCLIM_URL.format(resolution=args.worldclim_resolution)
        destination = args.output_dir / "worldclim" / f"wc2.1_{args.worldclim_resolution}_prec.zip"
        if args.list_only:
            print(url)
        else:
            print(f"Downloading WorldClim: {url}")
            record = download_file(url, destination, args.retries)
            check_zip(destination)
            record.update({"dataset": "WorldClim v2.1", "type": "monthly_precipitation_zip"})
            records.append(record)
            print(f"Verified ZIP: {destination}")

    if args.dataset in ("chelsa", "both"):
        for month in args.months:
            month_text = f"{month:02d}"
            url = args.chelsa_url_template.format(month=month_text)
            destination = args.output_dir / "chelsa" / f"CHELSA_pr_1981-2010_{month_text}.tif"
            if args.list_only:
                print(url)
                continue
            print(f"Downloading CHELSA month {month_text}: {url}")
            record = download_file(url, destination, args.retries)
            record.update({"dataset": "CHELSA v2.1", "month": month, "type": "monthly_precipitation_geotiff"})
            records.append(record)

    if not args.list_only:
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "arguments": {key: str(value) for key, value in vars(args).items()},
            "files": records,
        }
        manifest_path = args.output_dir / "download_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Wrote manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
