"""Geometry utilities for AOI processing."""
import re
import geopandas as gpd
from shapely.geometry import shape


def normalize_aoi_name(raw_name):
    """
    Normalize AOI name by removing prefixes and suffixes.

    Args:
        raw_name: Raw AOI name

    Returns:
        Normalized name
    """
    cleaned = re.sub(r"^(DrySpy_)?AOI_", "", raw_name)
    cleaned = re.sub(r"_(central|north|south|east|west)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def load_geojson(geojson_path):
    """
    Load GeoJSON file and return geometry and area.

    Args:
        geojson_path: Path to GeoJSON file

    Returns:
        tuple: (geometry_object, geojson_dict, area_sqkm)
    """
    gdf = gpd.read_file(geojson_path)
    gdf = gdf.to_crs(epsg=4326)
    aoi_geom = gdf.geometry.union_all()
    aoi_geojson = aoi_geom.__geo_interface__

    # Calculate area in sq km using equal-area CRS
    gdf_equal_area = gdf.to_crs(epsg=6933)  # World Cylindrical Equal Area
    area_sqkm = gdf_equal_area.area.sum() / 1e6  # m² → km²

    return aoi_geom, aoi_geojson, area_sqkm


def calculate_coverage(feature_geom, aoi_geom):
    """
    Calculate how much of AOI is covered by a feature.

    Args:
        feature_geom: Feature geometry (GeoJSON)
        aoi_geom: AOI geometry (shapely)

    Returns:
        Coverage percentage (0-100)
    """
    geom = shape(feature_geom)
    intersect_area = geom.intersection(aoi_geom).area
    coverage_pct = (intersect_area / aoi_geom.area) * 100
    return coverage_pct
