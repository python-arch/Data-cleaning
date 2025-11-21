"""
Core Transformers - POI ID, Name, Brand Detection
"""

import pandas as pd
import numpy as np
import re
from hashlib import md5
from typing import Optional, Dict, Any


class CoreTransformer:
    """
    Handles core POI transformations:
    - poi_id: MD5 hash of google_id
    - name: Business name cleaning
    - chain_flag: Chain detection (yes/no)
    - brand_name: Brand matching
    """

    def __init__(self, brand_config_df: Optional[pd.DataFrame] = None):
        """
        Initialize CoreTransformer

        Args:
            brand_config_df: DataFrame with brand configuration
                Expected columns: name, website_domain, original_category, brand_name
        """
        self.brand_config = brand_config_df
        self._build_brand_index()

    def _build_brand_index(self):
        """Build efficient lookup indexes for brand matching"""
        self.brand_by_name = {}
        self.brand_by_domain = {}
        self.brand_by_name_domain = {}

        if self.brand_config is not None:
            for _, row in self.brand_config.iterrows():
                name = str(row.get('name', '')).lower().strip()
                domain = str(row.get('website_domain', '')).lower().strip()
                brand = row.get('brand_name')

                if pd.notna(brand):
                    if name:
                        self.brand_by_name[name] = brand
                    if domain:
                        self.brand_by_domain[domain] = brand
                    if name and domain:
                        self.brand_by_name_domain[(name, domain)] = brand

    # ========================================================================
    # POI ID Generation
    # ========================================================================

    @staticmethod
    def hash_poi_id(text: Any) -> Optional[str]:
        """
        Generate MD5 hash of POI identifier

        Args:
            text: Source identifier (google_id)

        Returns:
            MD5 hash string or None
        """
        if pd.isna(text):
            return None
        return md5(str(text).encode('utf-8')).hexdigest()

    def transform_poi_id(self, df: pd.DataFrame) -> pd.Series:
        """Transform google_id to hashed poi_id"""
        return df['google_id'].apply(self.hash_poi_id)

    # ========================================================================
    # Name Cleaning
    # ========================================================================

    @staticmethod
    def clean_name(name: Any) -> Optional[str]:
        """
        Clean business name

        Args:
            name: Raw business name

        Returns:
            Cleaned name or None
        """
        if pd.isna(name):
            return None

        name_str = str(name).strip()

        # Remove excessive whitespace
        name_str = ' '.join(name_str.split())

        return name_str if name_str else None

    @staticmethod
    def is_valid_name(name: Any) -> bool:
        """
        Validate if name is meaningful

        Args:
            name: Business name to validate

        Returns:
            True if valid, False otherwise
        """
        if pd.isna(name):
            return False

        name_str = str(name).strip()

        # Empty name
        if not name_str:
            return False

        # Pure numbers
        if re.match(r'^\d+$', name_str):
            return False

        # Coordinates pattern
        if re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name_str):
            return False

        # Ratio pattern (e.g., "123 / 456")
        if re.match(r'^\d+\s*/\s*\d+$', name_str):
            return False

        # No meaningful characters
        meaningful_chars = re.sub(r'[^\w]', '', name_str)
        if not meaningful_chars:
            return False

        # Repeated single character
        if len(set(meaningful_chars)) == 1 and len(meaningful_chars) > 2:
            return False

        return True

    def is_valid_name_vectorized(self, names: pd.Series) -> pd.Series:
        """Vectorized name validation"""
        return names.apply(self.is_valid_name)

    # ========================================================================
    # Chain Detection
    # ========================================================================

    def detect_chain(self, row: pd.Series) -> str:
        """
        Detect if POI is a chain business

        Args:
            row: DataFrame row with name, website_domain

        Returns:
            'yes' if chain, 'no' otherwise
        """
        brand = self.match_brand(row)
        return 'yes' if brand else 'no'

    def match_brand(self, row: pd.Series) -> Optional[str]:
        """
        Match POI to brand name

        Args:
            row: DataFrame row with name, website_domain, category

        Returns:
            Brand name or None
        """
        if self.brand_config is None:
            return None

        name = str(row.get('name', '')).lower().strip()
        domain = str(row.get('website_domain', '')).lower().strip()

        # Try exact match on name + domain first
        if (name, domain) in self.brand_by_name_domain:
            return self.brand_by_name_domain[(name, domain)]

        # Try name match
        if name in self.brand_by_name:
            return self.brand_by_name[name]

        # Try domain match
        if domain in self.brand_by_domain:
            return self.brand_by_domain[domain]

        return None

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all core transformations to a DataFrame

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # POI ID
        if 'google_id' in df.columns:
            result['poi_id'] = self.transform_poi_id(df)

        # Name cleaning (already clean in most cases)
        if 'name' in df.columns:
            result['name'] = df['name'].apply(self.clean_name)

        # Chain detection and brand matching
        result['chain_flag'] = df.apply(self.detect_chain, axis=1)
        result['brand_name'] = df.apply(self.match_brand, axis=1)

        return result

    def filter_valid_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter out rows with invalid names

        Args:
            df: Input DataFrame

        Returns:
            Filtered DataFrame
        """
        valid_mask = self.is_valid_name_vectorized(df['name'])
        return df[valid_mask].copy()
