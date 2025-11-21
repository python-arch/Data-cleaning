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

    # Column name mappings for flexible schema support
    NAME_COLUMNS = ['name', 'poi_name', 'business_name', 'place_name']
    DOMAIN_COLUMNS = ['website_domain', 'domain', 'website', 'web_domain']
    BRAND_COLUMNS = ['brand_name', 'brand', 'chain_name', 'parent_brand']
    CATEGORY_COLUMNS = ['original_category', 'category', 'user_category', 'category_main']

    def __init__(self, brand_config_df: Optional[pd.DataFrame] = None):
        """
        Initialize CoreTransformer

        Args:
            brand_config_df: DataFrame with brand configuration
                Flexible schema - supports various column names:
                - Name: name, poi_name, business_name, place_name
                - Domain: website_domain, domain, website, web_domain
                - Brand: brand_name, brand, chain_name, parent_brand
                - Category: original_category, category, user_category
        """
        self.brand_config = brand_config_df
        self._column_mapping = {}
        self._build_brand_index()

    def _find_column(self, df: pd.DataFrame, candidates: list) -> Optional[str]:
        """
        Find the first matching column name from candidates

        Args:
            df: DataFrame to search
            candidates: List of possible column names

        Returns:
            First matching column name or None
        """
        if df is None:
            return None
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def _clean_value(self, val: Any) -> str:
        """Clean and normalize a value for lookup"""
        if pd.isna(val) or val is None:
            return ''
        return str(val).lower().strip()

    def _build_brand_index(self):
        """Build efficient lookup indexes for brand matching with flexible column detection"""
        self.brand_by_name = {}
        self.brand_by_domain = {}
        self.brand_by_name_domain = {}

        if self.brand_config is None:
            return

        # Drop any unnamed columns (like index columns from CSV)
        cols_to_use = [c for c in self.brand_config.columns if not c.startswith('Unnamed')]

        # Detect column names
        name_col = self._find_column(self.brand_config, self.NAME_COLUMNS)
        domain_col = self._find_column(self.brand_config, self.DOMAIN_COLUMNS)
        brand_col = self._find_column(self.brand_config, self.BRAND_COLUMNS)

        # Store mapping for reference
        self._column_mapping = {
            'name': name_col,
            'domain': domain_col,
            'brand': brand_col,
        }

        if brand_col is None:
            # No brand column found, cannot build mapping
            return

        for _, row in self.brand_config.iterrows():
            try:
                brand = row.get(brand_col)
                if pd.isna(brand) or brand is None:
                    continue

                brand = str(brand).strip()
                if not brand:
                    continue

                # Get name and domain safely
                name = ''
                domain = ''

                if name_col:
                    name = self._clean_value(row.get(name_col))

                if domain_col:
                    domain = self._clean_value(row.get(domain_col))

                # Build lookup indexes
                if name:
                    self.brand_by_name[name] = brand
                if domain:
                    self.brand_by_domain[domain] = brand
                if name and domain:
                    self.brand_by_name_domain[(name, domain)] = brand

            except Exception:
                # Skip malformed rows
                continue

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
        Match POI to brand name using multiple lookup strategies

        Args:
            row: DataFrame row with name, website_domain, category

        Returns:
            Brand name or None
        """
        if self.brand_config is None:
            return None

        # Check if any lookup index is available
        if not self.brand_by_name and not self.brand_by_domain and not self.brand_by_name_domain:
            return None

        # Safely extract name and domain
        name_val = row.get('name')
        domain_val = row.get('website_domain')

        name = self._clean_value(name_val)
        domain = self._clean_value(domain_val)

        # Strategy 1: Exact match on name + domain (highest confidence)
        if name and domain and (name, domain) in self.brand_by_name_domain:
            return self.brand_by_name_domain[(name, domain)]

        # Strategy 2: Try name match
        if name and name in self.brand_by_name:
            return self.brand_by_name[name]

        # Strategy 3: Try domain match
        if domain and domain in self.brand_by_domain:
            return self.brand_by_domain[domain]

        # Strategy 4: Try partial domain match (for subdomains)
        if domain:
            # Extract base domain (e.g., "store.example.com" -> "example.com")
            domain_parts = domain.split('.')
            if len(domain_parts) > 2:
                base_domain = '.'.join(domain_parts[-2:])
                if base_domain in self.brand_by_domain:
                    return self.brand_by_domain[base_domain]

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
