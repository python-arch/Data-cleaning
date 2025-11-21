"""Location transformations for coordinates and addresses."""

import pandas as pd
import numpy as np
import re
from typing import Optional, Tuple, Any


class LocationTransformer:
    """Handles coordinate validation, address cleaning, and postal codes."""

    USA_LAT_MIN = 24.0
    USA_LAT_MAX = 49.5
    USA_LON_MIN = -125.0
    USA_LON_MAX = -66.0

    US_POSTCODE_PATTERN = re.compile(r'^\d{5}(?:-\d{4})?$')

    def __init__(self, gadm_boundaries=None):
        self.gadm_boundaries = gadm_boundaries

    @staticmethod
    def add_coordinate_noise(value: Any) -> Optional[float]:
        """Add random noise to coordinate for privacy (2 digits after 6th decimal)."""
        if pd.isna(value):
            return value

        try:
            str_value = str(value)

            if 'e' in str_value.lower():
                return value

            if not (str_value.replace('.', '', 1).replace('-', '', 1).lstrip('+').isdigit()):
                return value

            random_digits = np.random.randint(10, 99)

            if "." in str_value:
                int_part, dec_part = str_value.split(".")
                if len(dec_part) > 6:
                    dec_part = dec_part[:6]
                elif len(dec_part) < 6:
                    dec_part = dec_part.ljust(6, "0")
            else:
                int_part = str_value
                dec_part = "000000"

            new_value_str = f"{int_part}.{dec_part}{random_digits}"
            return float(new_value_str)

        except Exception:
            return value

    @staticmethod
    def validate_coordinates(lat: Any, lon: Any) -> bool:
        """Check if coordinates are within valid global range."""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            return -90 <= lat_f <= 90 and -180 <= lon_f <= 180
        except (TypeError, ValueError):
            return False

    def is_within_usa(self, lat: Any, lon: Any) -> bool:
        """Check if coordinates are within continental USA."""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            return (self.USA_LAT_MIN <= lat_f <= self.USA_LAT_MAX and
                    self.USA_LON_MIN <= lon_f <= self.USA_LON_MAX)
        except (TypeError, ValueError):
            return False

    def is_outside_usa_vectorized(self, lats: pd.Series, lons: pd.Series) -> pd.Series:
        """Vectorized check for coordinates outside USA."""
        return (lats.isna() | lons.isna() |
                (lats < self.USA_LAT_MIN) | (lats > self.USA_LAT_MAX) |
                (lons < self.USA_LON_MIN) | (lons > self.USA_LON_MAX))

    @staticmethod
    def clean_address(address: Any) -> Optional[str]:
        """Clean address by removing plus code prefixes."""
        if pd.isna(address) or not isinstance(address, str):
            return address

        if '+' in address and ',' in address:
            parts = address.split(', ')
            if parts[0].count('+') >= 1:
                return ', '.join(parts[1:])

        return address

    @staticmethod
    def has_http_in_address(address: Any) -> bool:
        """Check if address contains HTTP (invalid)"""
        if pd.isna(address):
            return False
        return 'http' in str(address).lower()

    def has_http_in_address_vectorized(self, addresses: pd.Series) -> pd.Series:
        """Vectorized HTTP detection in addresses."""
        return addresses.str.contains('http', case=False, na=False)

    def validate_us_postcode(self, postcode: Any) -> bool:
        """Check if postal code matches US format (5 or 5+4 digits)."""
        if pd.isna(postcode):
            return False
        return bool(self.US_POSTCODE_PATTERN.match(str(postcode).strip()))

    def validate_us_postcode_vectorized(self, postcodes: pd.Series) -> pd.Series:
        """Vectorized postal code validation."""
        return postcodes.apply(self.validate_us_postcode)

    @staticmethod
    def extract_postcode_from_address(address: Any) -> Optional[str]:
        """Extract US postal code from address string."""
        if pd.isna(address):
            return None

        matches = re.findall(r'\b\d{5}(?:-\d{4})?\b', str(address))
        return matches[-1] if matches else None

    def extract_postcode_vectorized(self, addresses: pd.Series) -> pd.Series:
        """Vectorized postal code extraction."""
        return addresses.apply(self.extract_postcode_from_address)

    def fix_postcodes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fix missing or invalid postcodes by extracting from address."""
        result = df.copy()

        result['postal_code'] = result['postcode'].astype(str).replace('nan', '')
        result['postal_code'] = result['postal_code'].replace('', None)

        invalid_mask = ~self.validate_us_postcode_vectorized(result['postal_code'])

        if invalid_mask.any():
            invalid_indices = result[invalid_mask].index
            extracted = self.extract_postcode_vectorized(result.loc[invalid_indices, 'address'])
            valid_extracted = self.validate_us_postcode_vectorized(extracted)

            valid_indices = invalid_indices[valid_extracted]
            result.loc[valid_indices, 'postal_code'] = extracted[valid_extracted].values

            invalid_indices = invalid_indices[~valid_extracted]
            result.loc[invalid_indices, 'postal_code'] = None

        return result

    def apply_gadm_boundaries(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply GADM spatial join to correct region/locality from coordinates.

        Uses GADM administrative boundaries to derive accurate region (state/province)
        and locality (city/county) values from coordinates instead of using source data.

        Args:
            df: DataFrame with latitude and longitude columns

        Returns:
            DataFrame with region and locality columns derived from GADM
        """
        if self.gadm_boundaries is None:
            return df

        import geopandas as gpd

        gdf = gpd.GeoDataFrame(
            df.copy(),
            geometry=gpd.points_from_xy(df.longitude, df.latitude),
            crs="EPSG:4326",
        )

        gdf = gpd.sjoin(gdf, self.gadm_boundaries, how='left', predicate="within")

        # Rename old columns if they exist to avoid conflicts
        if "region" in gdf.columns:
            gdf.rename(columns={"region": "old_region"}, inplace=True)
        if "locality" in gdf.columns:
            gdf.rename(columns={"locality": "old_locality"}, inplace=True)

        # Map GADM columns to target schema
        # NAME_1 = first-level admin division (state/province) -> region
        # NAME_2 = second-level admin division (city/county) -> locality
        if "NAME_1" in gdf.columns:
            gdf.rename(columns={"NAME_1": "region"}, inplace=True)
        if "NAME_2" in gdf.columns:
            gdf.rename(columns={"NAME_2": "locality"}, inplace=True)

        columns_to_drop = ["old_region", "old_locality", "index_right", "geometry"]
        gdf.drop(columns=[col for col in columns_to_drop if col in gdf.columns], inplace=True)

        return pd.DataFrame(gdf)

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all location transformations to a DataFrame.

        Transforms include:
        - Address cleaning (removing plus code prefixes)
        - Country code mapping
        - Postal code validation and extraction
        - Coordinate noise addition for privacy
        - Region/locality cleaning via GADM boundaries (if available)

        Note: region and locality are derived from GADM boundaries using coordinates,
        not directly from source columns. This ensures accurate administrative
        division mapping.
        """
        result = df.copy()

        if 'address' in df.columns:
            result['address_full'] = df['address'].apply(self.clean_address)

        if 'country' in df.columns:
            result['country_code'] = df['country']
            result['country_isocode'] = df['country']

        if 'postcode' in df.columns and 'address' in df.columns:
            result = self.fix_postcodes(result)

        if 'latitude' in df.columns:
            result['latitude'] = df['latitude'].apply(self.add_coordinate_noise)
        if 'longitude' in df.columns:
            result['longitude'] = df['longitude'].apply(self.add_coordinate_noise)

        # Apply GADM boundaries to derive region/locality from coordinates
        # This replaces direct source mapping for accurate administrative divisions
        result = self.apply_gadm_boundaries(result)

        return result

    def filter_valid_locations(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter out rows with invalid locations."""
        lat_valid = pd.to_numeric(df['latitude'], errors='coerce')
        lon_valid = pd.to_numeric(df['longitude'], errors='coerce')

        valid_coords = lat_valid.notna() & lon_valid.notna()
        valid_bounds = (lat_valid >= -90) & (lat_valid <= 90) & (lon_valid >= -180) & (lon_valid <= 180)
        within_usa = ~self.is_outside_usa_vectorized(lat_valid, lon_valid)

        valid_address = ~self.has_http_in_address_vectorized(df['address']) if 'address' in df.columns else True

        return df[valid_coords & valid_bounds & within_usa & valid_address].copy()
