"""Planet API client with pagination and caching support."""
import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from flowzero.config import config


class PlanetAPIClient:
    """Client for interacting with Planet Labs API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or config.pl_api_key
        if not self.api_key:
            raise ValueError("Planet API key not configured")

        self.base_url = config.planet_base_url
        self.session = requests.Session()
        self.session.auth = (self.api_key, "")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(requests.RequestException),
    )
    def _request(self, method, url, **kwargs):
        """Make HTTP request with retry logic."""
        kwargs.setdefault("timeout", config.api_timeout)
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    def search_scenes(self, aoi_geojson, start_date_iso, end_date_iso, product_bundle):
        """
        Search for scenes with automatic pagination handling.

        Args:
            aoi_geojson: Area of interest as GeoJSON geometry
            start_date_iso: Start date in ISO format (YYYY-MM-DDTHH:MM:SSZ)
            end_date_iso: End date in ISO format
            product_bundle: Product bundle name (e.g., 'ortho_analytic_4b_sr')

        Returns:
            List of all features from all pages
        """
        search_url = f"{self.base_url}/data/v1/quick-search"
        search_payload = {
            "item_types": ["PSScene"],
            "filter": {
                "type": "AndFilter",
                "config": [
                    {"type": "GeometryFilter", "field_name": "geometry", "config": aoi_geojson},
                    {
                        "type": "DateRangeFilter",
                        "field_name": "acquired",
                        "config": {"gte": start_date_iso, "lte": end_date_iso},
                    },
                    {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": 0.0}},
                    {"type": "AssetFilter", "config": [product_bundle]},
                    {
                        "type": "StringInFilter",
                        "field_name": "quality_category",
                        "config": ["standard"],
                    },
                ],
            },
        }

        return self._fetch_all_pages(search_url, search_payload)

    def _fetch_all_pages(self, search_url, search_payload):
        """
        Fetch all pages of search results.

        Planet API uses pagination with _next link. Keep following until no more pages.
        """
        all_features = []
        current_url = search_url
        is_first_request = True

        while True:
            if is_first_request:
                response = self._request("POST", current_url, json=search_payload)
                is_first_request = False
            else:
                response = self._request("GET", current_url)

            data = response.json()
            features = data.get("features", [])
            all_features.extend(features)

            # Check for next page
            links = data.get("_links", {})
            next_url = links.get("_next")

            if next_url:
                current_url = next_url
                time.sleep(config.pagination_delay)
            else:
                break

        return all_features

    def submit_order(self, order_name, item_ids, product_bundle, aoi_geojson):
        """
        Submit an order to Planet API.

        Args:
            order_name: Name for the order
            item_ids: List of scene IDs to order
            product_bundle: Product bundle name
            aoi_geojson: GeoJSON geometry for clipping

        Returns:
            Order response JSON
        """
        order_url = f"{self.base_url}/compute/ops/orders/v2"
        order_payload = {
            "name": order_name,
            "products": [
                {"item_ids": item_ids, "item_type": "PSScene", "product_bundle": product_bundle}
            ],
            "tools": [{"clip": {"aoi": aoi_geojson}}],
        }

        response = self._request("POST", order_url, json=order_payload)
        return response.json()

    def get_order_status(self, order_id):
        """
        Get status of an order.

        Args:
            order_id: Planet order ID

        Returns:
            Order status JSON
        """
        url = f"{self.base_url}/compute/ops/orders/v2/{order_id}"
        response = self._request("GET", url)
        return response.json()

    def list_basemaps(self, start_date=None, end_date=None):
        """
        List available basemap mosaics, optionally filtered by date range.

        Args:
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)

        Returns:
            List of mosaic metadata
        """
        url = f"{self.base_url}/basemaps/v1/mosaics"
        all_mosaics = []

        while url:
            response = self._request("GET", url)
            data = response.json()
            mosaics = data.get("mosaics", [])
            all_mosaics.extend(mosaics)
            url = data.get("_links", {}).get("_next")

        if start_date and end_date:
            all_mosaics = [
                m
                for m in all_mosaics
                if start_date <= m.get("first_acquired", "")[:10] <= end_date
            ]

        return all_mosaics

    def order_basemap(self, mosaic_name, aoi_geojson):
        """
        Order a basemap mosaic.

        Args:
            mosaic_name: Name of the mosaic
            aoi_geojson: GeoJSON geometry for clipping

        Returns:
            Order response JSON
        """
        order_payload = {
            "name": f"Basemap Order {mosaic_name}",
            "source_type": "basemaps",
            "products": [{"mosaic_name": mosaic_name, "geometry": aoi_geojson}],
            "tools": [{"clip": {}}],
        }

        url = f"{self.base_url}/compute/ops/orders/v2"
        response = self._request("POST", url, json=order_payload)
        return response.json()
