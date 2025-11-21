"""
Location Transformers - Coordinates, Address, Geographic Validation
"""

import pandas as pd
import numpy as np
import re
from typing import Optional, Tuple, Any


class LocationTransformer:
    """
    Handles location-related transformations:
    - latitude/longitude: Coordinate validation and noise addition
    - address_full: Address cleaning
    - street, city, state, postal_code, country_code, country_isocode
    """

    # USA bounding box
    USA_LAT_MIN = 24.0
    USA_LAT_MAX = 49.5
    USA_LON_MIN = -125.0
    USA_LON_MAX = -66.0

    # Valid US postal code pattern
    US_POSTCODE_PATTERN = re.compile(r'^\d{5}(?:-\d{4})?$')

    def __init__(self, gadm_boundaries=None):
        """
        Initialize LocationTransformer

        Args:
            gadm_boundaries: GeoPandas GeoDataFrame with GADM admin boundaries
        """
        self.gadm_boundaries = gadm_boundaries

    # ========================================================================
    # Coordinate Transformations
    # ========================================================================

    @staticmethod
    def add_coordinate_noise(value: Any) -> Optional[float]:
        """
        Add random noise to coordinate (privacy protection)
        Adds 2 random digits after 6th decimal place

        Args:
            value: Latitude or longitude value

        Returns:
            Coordinate with noise added
        """
        if pd.isna(value):
            return value

        try:
            str_value = str(value)

            # Skip scientific notation
            if 'e' in str_value.lower():
                return value

            # Validate numeric
            if not (str_value.replace('.', '', 1).replace('-', '', 1).lstrip('+').isdigit()):
                return value

            random_digits = np.random.randint(10, 99)

            if "." in str_value:
                int_part, dec_part = str_value.split(".")
                # Truncate or pad to 6 decimal places
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
        """
        Validate coordinates are within valid global range

        Args:
            lat: Latitude value
            lon: Longitude value

        Returns:
            True if valid, False otherwise
        """
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            return -90 <= lat_f <= 90 and -180 <= lon_f <= 180
        except (TypeError, ValueError):
            return False

    def is_within_usa(self, lat: Any, lon: Any) -> bool:
        """
        Check if coordinates are within continental USA bounds

        Args:
            lat: Latitude value
            lon: Longitude value

        Returns:
            True if within USA, False otherwise
        """
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            return (self.USA_LAT_MIN <= lat_f <= self.USA_LAT_MAX and
                    self.USA_LON_MIN <= lon_f <= self.USA_LON_MAX)
        except (TypeError, ValueError):
            return False

    def is_outside_usa_vectorized(self, lats: pd.Series, lons: pd.Series) -> pd.Series:
        """
        Vectorized check for coordinates outside USA

        Args:
            lats: Series of latitudes
            lons: Series of longitudes

        Returns:
            Boolean Series (True if outside USA)
        """
        return (lats.isna() | lons.isna() |
                (lats < self.USA_LAT_MIN) | (lats > self.USA_LAT_MAX) |
                (lons < self.USA_LON_MIN) | (lons > self.USA_LON_MAX))

    # ========================================================================
    # Address Transformations
    # ========================================================================

    @staticmethod
    def clean_address(address: Any) -> Optional[str]:
        """
        Clean address string

        Args:
            address: Raw address string

        Returns:
            Cleaned address
        """
        if pd.isna(address) or not isinstance(address, str):
            return address

        # Remove plus code prefix if present
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
        """Vectorized HTTP detection in addresses"""
        return addresses.str.contains('http', case=False, na=False)

    # ========================================================================
    # Postal Code Transformations
    # ========================================================================

    def validate_us_postcode(self, postcode: Any) -> bool:
        """
        Validate US postal code format

        Args:
            postcode: Postal code string

        Returns:
            True if valid US format
        """
        if pd.isna(postcode):
            return False
        return bool(self.US_POSTCODE_PATTERN.match(str(postcode).strip()))

    def validate_us_postcode_vectorized(self, postcodes: pd.Series) -> pd.Series:
        """Vectorized postal code validation"""
        return postcodes.apply(self.validate_us_postcode)

    @staticmethod
    def extract_postcode_from_address(address: Any) -> Optional[str]:
        """
        Extract US postal code from address string

        Args:
            address: Full address string

        Returns:
            Extracted postal code or None
        """
        if pd.isna(address):
            return None

        # Find all 5-digit or 5+4 digit patterns
        matches = re.findall(r'\b\d{5}(?:-\d{4})?\b', str(address))
        return matches[-1] if matches else None

    def extract_postcode_vectorized(self, addresses: pd.Series) -> pd.Series:
        """Vectorized postal code extraction"""
        return addresses.apply(self.extract_postcode_from_address)

    def fix_postcodes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fix missing or invalid postcodes by extracting from address

        Args:
            df: DataFrame with 'postcode' and 'address' columns

        Returns:
            DataFrame with fixed postcodes
        """
        result = df.copy()

        # Convert postcode to string and clean
        result['postal_code'] = result['postcode'].astype(str).replace('nan', '')
        result['postal_code'] = result['postal_code'].replace('', None)

        # Find invalid postcodes
        invalid_mask = ~self.validate_us_postcode_vectorized(result['postal_code'])

        if invalid_mask.any():
            # Extract from address
            invalid_indices = result[invalid_mask].index
            extracted = self.extract_postcode_vectorized(result.loc[invalid_indices, 'address'])
            valid_extracted = self.validate_us_postcode_vectorized(extracted)

            # Update valid extractions
            valid_indices = invalid_indices[valid_extracted]
            result.loc[valid_indices, 'postal_code'] = extracted[valid_extracted].values

            # Set remaining invalid to None
            invalid_indices = invalid_indices[~valid_extracted]
            result.loc[invalid_indices, 'postal_code'] = None

        return result

    # ========================================================================
    # GADM Spatial Join
    # ========================================================================

    def apply_gadm_boundaries(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply GADM spatial join to correct region/locality based on coordinates

        Args:
            df: DataFrame with latitude, longitude columns

        Returns:
            DataFrame with corrected region/locality from GADM
        """
        if self.gadm_boundaries is None:
            return df

        import geopandas as gpd

        # Create GeoDataFrame from coordinates
        gdf = gpd.GeoDataFrame(
            df.copy(),
            geometry=gpd.points_from_xy(df.longitude, df.latitude),
            crs="EPSG:4326",
        )

        # Perform spatial join
        gdf = gpd.sjoin(gdf, self.gadm_boundaries, predicate="within")

        # Rename GADM columns
        if "NAME_1" in gdf.columns:
            gdf.rename(columns={"NAME_1": "state"}, inplace=True)
        if "NAME_2" in gdf.columns:
            gdf.rename(columns={"NAME_2": "city"}, inplace=True)

        # Clean up
        columns_to_drop = ["index_right", "geometry"]
        gdf.drop(columns=[col for col in columns_to_drop if col in gdf.columns], inplace=True)

        return pd.DataFrame(gdf)

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all location transformations to a DataFrame

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Clean address
        if 'address' in df.columns:
            result['address_full'] = df['address'].apply(self.clean_address)

        # Map location fields
        if 'locality' in df.columns:
            result['city'] = df['locality']
        if 'region_level_1' in df.columns:
            result['state'] = df['region_level_1']
        if 'country' in df.columns:
            result['country_code'] = df['country']
            result['country_isocode'] = df['country']

        # Fix postcodes
        if 'postcode' in df.columns and 'address' in df.columns:
            result = self.fix_postcodes(result)

        # Add coordinate noise
        if 'latitude' in df.columns:
            result['latitude'] = df['latitude'].apply(self.add_coordinate_noise)
        if 'longitude' in df.columns:
            result['longitude'] = df['longitude'].apply(self.add_coordinate_noise)

        return result

    def filter_valid_locations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter out rows with invalid locations

        Args:
            df: Input DataFrame

        Returns:
            Filtered DataFrame with valid USA coordinates
        """
        # Remove invalid coordinates
        lat_valid = pd.to_numeric(df['latitude'], errors='coerce')
        lon_valid = pd.to_numeric(df['longitude'], errors='coerce')

        valid_coords = lat_valid.notna() & lon_valid.notna()
        valid_bounds = (lat_valid >= -90) & (lat_valid <= 90) & (lon_valid >= -180) & (lon_valid <= 180)
        within_usa = ~self.is_outside_usa_vectorized(lat_valid, lon_valid)

        # Remove HTTP in address
        valid_address = ~self.has_http_in_address_vectorized(df['address']) if 'address' in df.columns else True

        return df[valid_coords & valid_bounds & within_usa & valid_address].copy()
