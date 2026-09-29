from pathlib import Path
import xarray as xr
import rasterio
import rioxarray

def extract_month_data_from_era5_land(era5_land_file: Path, target_month: str) -> xr.Dataset:
    with xr.open_dataset(era5_land_file) as ds:

        # for name, da in ds.data_vars.items():
        #     print(f"Variable: {name}, shape: {da.shape}, dims: {da.dims}")
        
        if target_month in ds.valid_time.dt.strftime("%m").values:
            # print(f"Month {target_month} found in {era5_land_file}")
            month_data = ds.sel(valid_time=ds.valid_time.dt.strftime("%m") == target_month)
            # Each yearly file contributes one timestamp for the requested
            # month. Remove that singleton coordinate before concatenating
            # years; otherwise a second ``valid_time`` dimension survives the
            # mean and makes the raster four-dimensional.
            month_data = month_data.isel(valid_time=0, drop=True)
            return month_data.load()
        else:
            print(f"Month {target_month} not found in {era5_land_file}")
            return None

def cal_mean_era5_precipitation(era5_land_files: list[Path], target_month: str) -> xr.Dataset:

    months = []

    for era5_land_file in era5_land_files:
        month_data = extract_month_data_from_era5_land(era5_land_file, target_month)
        if month_data is not None:
            # Drop conflicting variables like 'expver' before concatenating
            if 'expver' in month_data.coords:
                month_data = month_data.drop_vars('expver')
            months.append(month_data)

    print(f"Extracted data for month {target_month} from {len(months)} files.")

    months_mean = xr.concat(months, dim="time").mean(dim="time")
    # months_mean.to_netcdf(f"data/era5_land/{target_month}_mean.nc")
    return months_mean

def read_worldclim_precipitation_data(
    file_path: Path, bounds: tuple[float, float, float, float]
) -> xr.DataArray:
    """Read the WorldClim raster over ``(west, south, east, north)``.

    Coordinates are stored as geographic pixel centers so that the ERA5
    coarse field can be interpolated onto exactly the same two dimensions.
    """
    west, south, east, north = bounds
    with rasterio.open(file_path) as src:
        window = rasterio.windows.from_bounds(west, south, east, north, src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(1, window=window).astype("float32")
        transform = src.window_transform(window)
        crs = src.crs
        if crs is None:
            raise ValueError(f"WorldClim raster has no CRS: {file_path}")

    rows = xr.DataArray(range(data.shape[0]), dims="latitude") + 0.5
    cols = xr.DataArray(range(data.shape[1]), dims="longitude") + 0.5
    lat = transform.f + rows * transform.e
    lon = transform.c + cols * transform.a
    return xr.DataArray(
        data,
        dims=("latitude", "longitude"),
        coords={"latitude": lat, "longitude": lon},
        attrs={"transform": transform, "crs": crs},
    )

def main():
    # Only use downloaded yearly files; ``01_mean.nc`` is a previous output
    # and must not be included in the baseline average.
    era5_land_files = sorted(Path("data/era5_land").glob("era5_land_tp_*.nc"))
    # The old output directory may have inherited read-only ACLs. Use a fresh
    # project-local directory that the current user can create and write.
    target_dir = Path("outputs/era5_land_downscaled")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_month = "01"

    target_year_files = Path("data/era5_land_target").glob("*.nc")

    worldclim_precipitation_file = Path(f"data/climate_baselines/worldclim/wc2.1_30s_prec_{target_month}.tif")

    era5_months_mean = cal_mean_era5_precipitation(era5_land_files, target_month)

    era5_target_years_mean = cal_mean_era5_precipitation(target_year_files, target_month)

    # Extract the precipitation variable from the datasets
    # Assuming the precipitation variable is 'tp' (total precipitation)
    era5_target_precip = era5_target_years_mean['tp'] if 'tp' in era5_target_years_mean else era5_target_years_mean[list(era5_target_years_mean.data_vars)[0]]
    era5_mean_precip = era5_months_mean['tp'] if 'tp' in era5_months_mean else era5_months_mean[list(era5_months_mean.data_vars)[0]]

    # Restrict WorldClim to the ERA5 domain, then interpolate both ERA5
    # fields onto its geographic pixel centers. This keeps the calculation
    # two-dimensional: (latitude, longitude).
    lat_values = era5_mean_precip.latitude.values
    lon_values = era5_mean_precip.longitude.values
    bounds = (
        float(lon_values.min()),
        float(lat_values.min()),
        float(lon_values.max()),
        float(lat_values.max()),
    )
    worldclim_precipitation = read_worldclim_precipitation_data(worldclim_precipitation_file, bounds)
    # ERA5 source files can have different grid extents. Restrict the target
    # field to the regional baseline domain before interpolation, and sort
    # both coordinates because ERA5 commonly stores latitude north-to-south.
    era5_mean_precip = era5_mean_precip.sortby("latitude").sortby("longitude")
    era5_target_precip = era5_target_precip.sortby("latitude").sortby("longitude")
    era5_target_precip = era5_target_precip.sel(
        latitude=slice(bounds[1], bounds[3]),
        longitude=slice(bounds[0], bounds[2]),
    )
    target_on_wc = era5_target_precip.interp(
        latitude=worldclim_precipitation.latitude,
        longitude=worldclim_precipitation.longitude,
    )
    mean_on_wc = era5_mean_precip.interp(
        latitude=worldclim_precipitation.latitude,
        longitude=worldclim_precipitation.longitude,
    )
    delta = target_on_wc / mean_on_wc
    print(f"Delta shape: {delta.shape}, dims: {delta.dims}")
    target_years_mean = worldclim_precipitation * (target_on_wc / mean_on_wc)

    # Squeeze the result to remove any single dimensions
    target_years_mean = target_years_mean.squeeze()

    print(f"Target years mean shape: {target_years_mean.shape}, dims: {target_years_mean.dims}")

    # Save using rioxarray
    # GeoTIFF nodata must be an explicit numeric value. Convert NaNs before
    # writing so viewers do not render missing cells as black valid data.
    nodata_value = -9999.0
    target_years_mean = target_years_mean.fillna(nodata_value)
    target_years_mean = target_years_mean.where(target_years_mean > 0, nodata_value)
    target_years_mean = target_years_mean.rio.write_crs(worldclim_precipitation.attrs["crs"])
    target_years_mean = target_years_mean.rio.write_nodata(nodata_value)
    target_years_mean.rio.set_spatial_dims(x_dim="longitude", y_dim="latitude", inplace=True)
    target_years_mean.rio.to_raster(
        target_dir / f"era5_downscaled_{target_month}.tif",
        driver="GTiff",
        nodata=nodata_value,
        dtype="float32",
        compress="deflate",
    )


if __name__=="__main__":
    main()
