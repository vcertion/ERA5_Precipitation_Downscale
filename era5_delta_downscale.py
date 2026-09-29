#!/usr/bin/env python3
"""Multiplicative Delta downscaling of ERA5-Land precipitation with WorldClim.

For each target year/month this computes::

    WorldClim_monthly_precip * ERA5_target_month / ERA5_baseline_month

ERA5 monthly-means total precipitation is converted from mean daily metres to
monthly millimetres. The output is on the WorldClim grid (30 arc-sec is roughly
1 km at the equator). A final 250 m geographic grid can be requested, but it
is only a resampling of the 1 km estimate.
"""

from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject


def parse_years(value: str) -> list[int]:
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            result.extend(range(start, end + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def find_precip_var(dataset: xr.Dataset) -> str:
    for name in ("tp", "total_precipitation", "precipitation"):
        if name in dataset.data_vars:
            return name
    if len(dataset.data_vars) == 1:
        return next(iter(dataset.data_vars))
    raise ValueError(f"Cannot identify precipitation variable. Variables: {list(dataset.data_vars)}")


def find_coord(dataset: xr.Dataset, names: tuple[str, ...]) -> str:
    for name in names:
        if name in dataset.coords or name in dataset.dims:
            return name
    raise ValueError(f"Cannot identify coordinate among {names}; found {list(dataset.coords)}")


def load_era5(paths: list[Path]) -> xr.DataArray:
    datasets = [xr.open_dataset(path) for path in paths]
    try:
        variables = [find_precip_var(dataset) for dataset in datasets]
        arrays = []
        for dataset, variable in zip(datasets, variables):
            array = dataset[variable]
            time_name = find_coord(dataset, ("time", "valid_time", "date"))
            lat_name = find_coord(dataset, ("latitude", "lat"))
            lon_name = find_coord(dataset, ("longitude", "lon"))
            array = array.rename({time_name: "time", lat_name: "latitude", lon_name: "longitude"})
            arrays.append(array)
        result = xr.concat(arrays, dim="time").sortby("time")
    finally:
        for dataset in datasets:
            dataset.close()
    # xarray interpolation requires monotonic coordinates. ERA5 longitudes may
    # be 0..360, while WorldClim uses -180..180.
    if float(result.longitude.max()) > 180:
        longitude = ((result.longitude + 180) % 360) - 180
        result = result.assign_coords(longitude=longitude).sortby("longitude")
    result = result.sortby("latitude")
    return result


def read_worldclim(path: Path, bbox: tuple[float, float, float, float] | None) -> tuple[np.ndarray, rasterio.Affine, str, float | None]:
    with rasterio.open(path) as source:
        if bbox:
            west, south, east, north = bbox
            window = rasterio.windows.from_bounds(west, south, east, north, source.transform)
            window = window.round_offsets().round_lengths()
        else:
            window = rasterio.windows.Window(0, 0, source.width, source.height)
        data = source.read(1, window=window).astype("float32")
        transform = source.window_transform(window)
        nodata = source.nodata
        crs = source.crs
    if nodata is not None:
        data[data == nodata] = np.nan
    if crs is None:
        raise ValueError(f"WorldClim raster has no CRS: {path}")
    return data, transform, crs.to_string(), nodata


def worldclim_coords(data: np.ndarray, transform: rasterio.Affine) -> tuple[np.ndarray, np.ndarray]:
    rows = np.arange(data.shape[0]) + 0.5
    cols = np.arange(data.shape[1]) + 0.5
    lon = transform.c + cols * transform.a
    lat = transform.f + rows * transform.e
    return lat, lon


def write_geotiff(path: Path, data: np.ndarray, transform: rasterio.Affine, crs: str) -> None:
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": -9999.0,
        "compress": "deflate",
        "predictor": 2,
        "tiled": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as destination:
        destination.write(np.where(np.isfinite(data), data, -9999.0).astype("float32"), 1)


def resample_to_grid(data: np.ndarray, source_transform: rasterio.Affine, crs: str, resolution: float) -> tuple[np.ndarray, rasterio.Affine]:
    left = source_transform.c
    top = source_transform.f
    right = left + data.shape[1] * source_transform.a
    bottom = top + data.shape[0] * source_transform.e
    width = max(1, int(np.ceil((right - left) / resolution)))
    height = max(1, int(np.ceil((top - bottom) / resolution)))
    destination_transform = from_bounds(left, bottom, right, top, width, height)
    destination = np.full((height, width), np.nan, dtype="float32")
    reproject(
        source=np.where(np.isfinite(data), data, np.nan),
        destination=destination,
        src_transform=source_transform,
        src_crs=crs,
        dst_transform=destination_transform,
        dst_crs=crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return destination, destination_transform


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--era5-dir", type=Path, required=True)
    parser.add_argument("--worldclim-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-years", type=parse_years, required=True, help="e.g. 1970-2000")
    parser.add_argument("--target-years", type=parse_years, required=True, help="e.g. 2020-2022")
    parser.add_argument("--worldclim-resolution", default="30s")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--interpolation", choices=("linear", "nearest"), default="linear")
    parser.add_argument("--epsilon-mm", type=float, default=0.1, help="stabilizer for dry ERA5 baseline pixels")
    parser.add_argument("--delta-min", type=float, default=0.1)
    parser.add_argument("--delta-max", type=float, default=10.0)
    parser.add_argument("--era5-units", choices=("mean_daily_m", "monthly_total_m", "mean_daily_mm", "monthly_total_mm"), default="mean_daily_m")
    parser.add_argument("--fine-resolution-degrees", type=float, help="optional final geographic pixel size; 0.00225 is about 250 m at the equator")
    args = parser.parse_args()
    if args.epsilon_mm < 0 or args.delta_min < 0 or args.delta_max <= args.delta_min:
        parser.error("invalid epsilon or delta limits")

    era5_paths = [args.era5_dir / f"era5_land_tp_{year}.nc" for year in sorted(set(args.baseline_years + args.target_years))]
    missing = [str(path) for path in era5_paths if not path.exists()]
    if missing:
        parser.error("missing ERA5 files:\n" + "\n".join(missing))
    era5 = load_era5(era5_paths)
    if args.era5_units == "mean_daily_m":
        era5 = era5 * 1000.0 * era5.time.dt.days_in_month
    elif args.era5_units == "monthly_total_m":
        era5 = era5 * 1000.0
    elif args.era5_units == "mean_daily_mm":
        era5 = era5 * era5.time.dt.days_in_month

    baseline = era5.sel(time=era5.time.dt.year.isin(args.baseline_years))
    targets = era5.sel(time=era5.time.dt.year.isin(args.target_years))
    if baseline.time.size == 0 or targets.time.size == 0:
        parser.error("baseline or target years are absent from the ERA5 files")
    baseline_by_month = baseline.groupby("time.month").mean("time")

    reference_path = args.worldclim_dir / f"wc2.1_{args.worldclim_resolution}_prec_01.tif"
    if not reference_path.exists():
        parser.error(f"missing WorldClim raster: {reference_path}")
    reference_data, reference_transform, crs, _ = read_worldclim(reference_path, tuple(args.bbox) if args.bbox else None)
    reference_lat, reference_lon = worldclim_coords(reference_data, reference_transform)
    # WorldClim is north-to-south; xarray coordinates are sorted ascending.
    wc_lat_ascending = np.sort(reference_lat)
    wc_lon_ascending = np.sort(reference_lon)

    for target_time in targets.time.values:
        timestamp = np.datetime64(target_time, "D")
        year = int(str(timestamp)[:4])
        month = int(str(timestamp)[5:7])
        wc_path = args.worldclim_dir / f"wc2.1_{args.worldclim_resolution}_prec_{month:02d}.tif"
        worldclim, transform, output_crs, _ = read_worldclim(wc_path, tuple(args.bbox) if args.bbox else None)
        base_coarse = baseline_by_month.sel(month=month)
        target_coarse = era5.sel(time=target_time, method="nearest")
        base_high = base_coarse.interp(latitude=wc_lat_ascending, longitude=wc_lon_ascending, method=args.interpolation).values
        target_high = target_coarse.interp(latitude=wc_lat_ascending, longitude=wc_lon_ascending, method=args.interpolation).values
        delta = (target_high + args.epsilon_mm) / (base_high + args.epsilon_mm)
        delta = np.clip(delta, args.delta_min, args.delta_max)
        # Flip latitude because interpolation used ascending coordinates.
        high_data = worldclim * np.flipud(delta)
        output_path = args.output_dir / f"era5_delta_worldclim_{year}_{month:02d}_1km.tif"
        write_geotiff(output_path, high_data, transform, output_crs)
        if args.fine_resolution_degrees:
            fine_data, fine_transform = resample_to_grid(high_data, transform, output_crs, args.fine_resolution_degrees)
            fine_path = args.output_dir / f"era5_delta_worldclim_{year}_{month:02d}_fine_grid.tif"
            write_geotiff(fine_path, fine_data, fine_transform, output_crs)
        print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
