#!/usr/bin/env python3
"""Download ERA5-Land monthly total precipitation from Copernicus CDS.

The CDS monthly-means product stores total precipitation as a mean daily
accumulation. The companion downscaling script converts it to mm/month by
multiplying by the number of days in each month.

Before running, install cdsapi and configure the CDS API credentials according
to the current Copernicus documentation. The script makes one request per
year, which is easier to resume than one large multi-decade request.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DATASET = "reanalysis-era5-land-monthly-means"


def parse_years(value: str) -> list[int]:
    years: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError("year range must be ascending")
            years.extend(range(start, end + 1))
        else:
            years.append(int(part))
    result = sorted(set(years))
    if not result or any(year < 1950 or year > 2100 for year in result):
        raise argparse.ArgumentTypeError("years must be between 1950 and 2100")
    return result


def parse_months(value: str) -> list[str]:
    months = []
    for part in value.split(","):
        month = int(part.strip())
        if month < 1 or month > 12:
            raise argparse.ArgumentTypeError("months must be integers from 1 to 12")
        text = f"{month:02d}"
        if text not in months:
            months.append(text)
    return months


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=parse_years, required=True, help="e.g. 1970-2000 or 2020,2021")
    parser.add_argument("--months", type=parse_months, default=[f"{m:02d}" for m in range(1, 13)])
    parser.add_argument("--output-dir", type=Path, default=Path("data/era5_land"))
    parser.add_argument(
        "--area",
        nargs=4,
        type=float,
        metavar=("NORTH", "WEST", "SOUTH", "EAST"),
        help="optional CDS area in degrees; order is north west south east",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        import cdsapi
    except ImportError as exc:
        parser.error("cdsapi is not installed. Install it with: python -m pip install cdsapi")
        raise AssertionError from exc

    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()
    records: list[dict] = []

    for year in args.years:
        destination = args.output_dir / f"era5_land_tp_{year}.nc"
        if destination.exists() and not args.overwrite:
            print(f"Skipping existing file: {destination}")
            records.append({"year": year, "path": str(destination), "status": "existing"})
            continue

        request = {
            "product_type": "monthly_averaged_reanalysis",
            "variable": ["total_precipitation"],
            "year": [str(year)],
            "month": args.months,
            "time": ["00:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        if args.area:
            request["area"] = args.area

        print(f"Requesting ERA5-Land {year}: {destination}")
        client.retrieve(DATASET, request, str(destination))
        if not destination.exists() or destination.stat().st_size == 0:
            raise RuntimeError(f"CDS returned no usable file: {destination}")
        records.append({"year": year, "path": str(destination), "status": "downloaded"})

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET,
        "notes": "total_precipitation is interpreted as mean daily accumulation by the downscaling script",
        "arguments": {key: str(value) for key, value in vars(args).items()},
        "files": records,
    }
    manifest_path = args.output_dir / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
