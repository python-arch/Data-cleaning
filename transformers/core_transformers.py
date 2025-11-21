"""Core Transformers - POI ID, Name, Brand Detection"""

import logging
import pandas as pd
import numpy as np
import re
from hashlib import md5
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CoreTransformer:
    """Handles core POI transformations: poi_id, name, chain_flag, brand_name."""

    REQUIRED_BRAND_COLUMNS = ['name', 'website_domain', 'brand_name']

    def __init__(self, brand_config_df: Optional[pd.DataFrame] = None):
        self.brand_config = brand_config_df
        self._validate_brand_config()
        self._build_brand_index()

    def _validate_brand_config(self):
        """Validate brand config has required columns."""
        if self.brand_config is None:
            logger.info("No brand config provided, chain detection disabled")
            return

        missing = [c for c in self.REQUIRED_BRAND_COLUMNS if c not in self.brand_config.columns]
        if missing:
            raise ValueError(f"Brand config missing required columns: {missing}. "
                           f"Expected: {self.REQUIRED_BRAND_COLUMNS}")

        logger.info(f"Brand config validated: {len(self.brand_config)} entries")

    def _clean_value(self, val: Any) -> str:
        if pd.isna(val) or val is None:
            return ''
        return str(val).lower().strip()

    def _build_brand_index(self):
        """Build lookup indexes for brand matching."""
        self.brand_by_name = {}
        self.brand_by_domain = {}
        self.brand_by_name_domain = {}

        if self.brand_config is None:
            return

        for _, row in self.brand_config.iterrows():
            try:
                brand = row['brand_name']
                if pd.isna(brand) or not str(brand).strip():
                    continue

                brand = str(brand).strip()
                name = self._clean_value(row['name'])
                domain = self._clean_value(row['website_domain'])

                if name:
                    self.brand_by_name[name] = brand
                if domain:
                    self.brand_by_domain[domain] = brand
                if name and domain:
                    self.brand_by_name_domain[(name, domain)] = brand

            except Exception as e:
                logger.debug(f"Skipping malformed brand row: {e}")
                continue

        logger.info(f"Brand index built: {len(self.brand_by_name)} names, "
                   f"{len(self.brand_by_domain)} domains")

    @staticmethod
    def hash_poi_id(text: Any) -> Optional[str]:
        if pd.isna(text):
            return None
        return md5(str(text).encode('utf-8')).hexdigest()

    def transform_poi_id(self, df: pd.DataFrame) -> pd.Series:
        if 'google_id' not in df.columns:
            raise ValueError("Missing required column: google_id")
        return df['google_id'].apply(self.hash_poi_id)

    @staticmethod
    def clean_name(name: Any) -> Optional[str]:
        if pd.isna(name):
            return None
        name_str = str(name).strip()
        name_str = ' '.join(name_str.split())
        return name_str if name_str else None

    @staticmethod
    def is_valid_name(name: Any) -> bool:
        if pd.isna(name):
            return False

        name_str = str(name).strip()
        if not name_str:
            return False

        if re.match(r'^\d+$', name_str):
            return False

        if re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name_str):
            return False

        if re.match(r'^\d+\s*/\s*\d+$', name_str):
            return False

        meaningful_chars = re.sub(r'[^\w]', '', name_str)
        if not meaningful_chars:
            return False

        if len(set(meaningful_chars)) == 1 and len(meaningful_chars) > 2:
            return False

        return True

    def is_valid_name_vectorized(self, names: pd.Series) -> pd.Series:
        return names.apply(self.is_valid_name)

    def detect_chain(self, row: pd.Series) -> str:
        brand = self.match_brand(row)
        return 'yes' if brand else 'no'

    def match_brand(self, row: pd.Series) -> Optional[str]:
        if self.brand_config is None:
            return None

        if not self.brand_by_name and not self.brand_by_domain:
            return None

        name = self._clean_value(row.get('name'))
        domain = self._clean_value(row.get('website_domain'))

        if name and domain and (name, domain) in self.brand_by_name_domain:
            return self.brand_by_name_domain[(name, domain)]

        if name and name in self.brand_by_name:
            return self.brand_by_name[name]

        if domain and domain in self.brand_by_domain:
            return self.brand_by_domain[domain]

        if domain:
            domain_parts = domain.split('.')
            if len(domain_parts) > 2:
                base_domain = '.'.join(domain_parts[-2:])
                if base_domain in self.brand_by_domain:
                    return self.brand_by_domain[base_domain]

        return None

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()

        if 'google_id' not in df.columns:
            raise ValueError("Missing required column: google_id")
        result['poi_id'] = self.transform_poi_id(df)

        if 'name' not in df.columns:
            raise ValueError("Missing required column: name")
        result['name'] = df['name'].apply(self.clean_name)

        result['chain_flag'] = df.apply(self.detect_chain, axis=1)
        result['brand_name'] = df.apply(self.match_brand, axis=1)

        return result

    def filter_valid_names(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'name' not in df.columns:
            raise ValueError("Missing required column: name")
        valid_mask = self.is_valid_name_vectorized(df['name'])
        return df[valid_mask].copy()
