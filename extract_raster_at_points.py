#!/usr/bin/env python3
"""Extract GeoTIFF values at point features and save a CSV table.

Example:
    python extract_raster_at_points.py --points data/stations.gpkg \
        --raster outputs/era5_land_downscaled_250m/era5_downscaled_07_250m.tif \
        --output outputs/station_raster_values.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True, help="Point Shapefile, GeoPackage, or GeoJSON")
    parser.add_argument("--raster", type=Path, nargs="+", required=True, help="One or more GeoTIFF files")
    parser.add_argument("--output", type=Path, required=True, help="Output CSV file")
    parser.add_argument("--band", type=int, default=1, help="Band number to sample (default: 1)")
    return parser.parse_args()


def sample_raster(points: gpd.GeoDataFrame, raster_path: Path, band: int) -> list[float]:
    with rasterio.open(raster_path) as source:
        if source.crs is None:
            raise ValueError(f"Raster has no CRS: {raster_path}")
        if not 1 <= band <= source.count:
            raise ValueError(f"Band {band} does not exist in {raster_path}; available: 1-{source.count}")

        projected = points.to_crs(source.crs)
        coordinates = [(point.x, point.y) for point in projected.geometry]
        values: list[float] = []

        for (x, y), sample in zip(
            coordinates, source.sample(coordinates, indexes=band, masked=True)
        ):
            row, col = source.index(x, y)
            if row < 0 or row >= source.height or col < 0 or col >= source.width:
                values.append(float("nan"))
                continue

            value = sample[0]
            if np.ma.is_masked(value) or not np.isfinite(value):
                values.append(float("nan"))
            else:
                values.append(float(value))
        return values


def main() -> int:
    args = parse_args()
    if not args.points.is_file():
        raise FileNotFoundError(args.points)

    points = gpd.read_file(args.points)
    if points.crs is None:
        raise ValueError("Point vector has no CRS. Define its actual CRS before extracting values.")
    if points.empty:
        raise ValueError("Point vector contains no features")
    if points.geometry.isna().any() or points.geometry.is_empty.any():
        raise ValueError("Point vector contains missing or empty geometries")
    if not points.geometry.geom_type.eq("Point").all():
        raise ValueError("All features must have Point geometries")

    table = pd.DataFrame(points.drop(columns=points.geometry.name))
    table.insert(0, "point_x", points.geometry.x.to_numpy())
    table.insert(1, "point_y", points.geometry.y.to_numpy())
    table.insert(2, "point_crs", points.crs.to_string())

    for raster_path in args.raster:
        if not raster_path.is_file():
            raise FileNotFoundError(raster_path)
        column = raster_path.stem
        if column in table.columns:
            raise ValueError(f"Duplicate output column '{column}'; use raster files with distinct names")
        table[column] = sample_raster(points, raster_path, args.band)
        print(f"Sampled {raster_path}: {table[column].notna().sum()}/{len(table)} valid points")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
