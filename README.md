# ERA5 Precipitation Downscaling / ERA5降水降尺度

## English

This project downscales monthly ERA5-Land precipitation using a WorldClim high-resolution precipitation baseline. It also provides utilities for reprojecting the result to a 250 m grid and sampling raster values at point locations.

### Features

- Download ERA5-Land monthly precipitation data.
- Download WorldClim precipitation baseline rasters.
- Calculate a monthly ERA5 target-to-baseline ratio.
- Apply the ratio to WorldClim and write a GeoTIFF.
- Reproject the result to a 250 m grid.
- Extract raster values at point features and save them as CSV.

### Requirements

Python 3.10 or newer is recommended. Install the main dependencies with:

```bash
pip install numpy pandas xarray rasterio rioxarray geopandas
```

The ERA5 download script may also require the Copernicus Climate Data Store client and valid CDS credentials.

### Main scripts

- `download_era5_land.py`: download ERA5-Land monthly data.
- `download_climate_baselines.py`: download WorldClim baseline data.
- `ERA5_DOWNSCALE.py`: calculate the downscaled precipitation raster and optionally reproject it to 250 m.
- `extract_raster_at_points.py`: sample one or more GeoTIFF files at point features.

### Typical workflow

Run commands from the repository root:

```bash
python download_era5_land.py
python download_climate_baselines.py
python ERA5_DOWNSCALE.py
```

The active entry point in `ERA5_DOWNSCALE.py` runs the 250 m reprojection function. To generate the intermediate downscaled raster first, call `downscale_2_1KM()` before calling `downscale_2_250m()` or invoke the functions from Python.

To sample point data:

```bash
python extract_raster_at_points.py \
  --points data/stations.gpkg \
  --raster outputs/era5_land_downscaled_250m/era5_downscaled_08_250m.tif \
  --output outputs/station_raster_values.csv
```

Input point data must contain a valid CRS and Point geometries. Raster outputs use `-9999` as the NoData value.

### Data and outputs

Downloaded NetCDF/GeoTIFF source data and generated products are ignored by Git because they can be large. Keep local data under `data/` and generated products under `outputs/`.

### Notes

The default configuration in the current script is tailored to the Yuzhong area and August precipitation. Review the input directories, month, geographic bounds, CRS, and target years before running it for another region.

## 中文说明

本项目使用 WorldClim 高分辨率降水基准数据，对 ERA5-Land 月尺度降水进行降尺度处理，并提供 250 m 重投影和点位栅格采样功能。

### 主要功能

- 下载 ERA5-Land 月尺度降水数据；
- 下载 WorldClim 降水基准栅格；
- 计算目标年份与历史基准的 ERA5 降水比值；
- 将比值应用到 WorldClim，输出 GeoTIFF；
- 将结果重投影到 250 m 网格；
- 根据点位矢量提取栅格值并保存为 CSV。

### 环境安装

建议使用 Python 3.10 及以上版本，并安装主要依赖：

```bash
pip install numpy pandas xarray rasterio rioxarray geopandas
```

ERA5 下载脚本还可能需要安装 Copernicus Climate Data Store 客户端，并配置有效的 CDS 账号信息。

### 主要脚本

- `download_era5_land.py`：下载 ERA5-Land 月数据；
- `download_climate_baselines.py`：下载 WorldClim 基准数据；
- `ERA5_DOWNSCALE.py`：计算降尺度降水栅格，并可重投影到 250 m；
- `extract_raster_at_points.py`：在点位处提取一个或多个 GeoTIFF 的栅格值。

### 基本流程

在项目根目录执行：

```bash
python download_era5_land.py
python download_climate_baselines.py
python ERA5_DOWNSCALE.py
```

当前 `ERA5_DOWNSCALE.py` 的入口默认执行 250 m 重投影。若尚未生成中间降尺度结果，应先运行 `downscale_2_1KM()`，再运行 `downscale_2_250m()`，也可以从 Python 中直接调用这两个函数。

点位采样示例：

```bash
python extract_raster_at_points.py \
  --points data/stations.gpkg \
  --raster outputs/era5_land_downscaled_250m/era5_downscaled_08_250m.tif \
  --output outputs/station_raster_values.csv
```

点位数据必须具有有效 CRS，且几何类型必须为 Point。栅格输出使用 `-9999` 表示 NoData。

### 数据和输出目录

下载的 NetCDF/GeoTIFF 源数据和生成结果可能较大，因此已加入 Git 忽略规则。建议将本地源数据放在 `data/`，生成结果放在 `outputs/`。

### 注意事项

当前脚本默认配置面向榆中区域和 8 月降水。应用到其他区域或月份前，请检查输入目录、月份、地理范围、坐标系和目标年份配置。
