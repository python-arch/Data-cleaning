"""Establishment transformations for parent location detection."""

import pandas as pd
import numpy as np
import re
from typing import Optional, Any, List


class EstablishmentTransformer:
    """Handles parent establishment detection and floor level normalization."""

    PARENT_TYPE_MAPPING = {
        # Mall/Shopping
        'shopping_mall': 'Mall',
        'shopping_center': 'Mall',
        'mall': 'Mall',
        'outlet_mall': 'Mall',
        'department_store': 'Mall',

        # Airports
        'airport': 'Airport',
        'airport_terminal': 'Airport',
        'international_airport': 'Airport',

        # Medical
        'hospital': 'Hospital',
        'medical_center': 'Hospital',
        'clinic': 'Hospital',
        'health_center': 'Hospital',

        # Education
        'university': 'Campus',
        'college': 'Campus',
        'school': 'Campus',
        'campus': 'Campus',

        # Hotels
        'hotel': 'Hotel',
        'resort': 'Hotel',
        'motel': 'Hotel',
        'inn': 'Hotel',

        # Entertainment
        'casino': 'Casino',
        'stadium': 'Stadium',
        'arena': 'Stadium',
        'sports_complex': 'Stadium',
        'convention_center': 'Convention Center',
        'conference_center': 'Convention Center',
        'amusement_park': 'Entertainment Complex',
        'theme_park': 'Entertainment Complex',

        # Transit
        'train_station': 'Transit Station',
        'railway_station': 'Transit Station',
        'bus_station': 'Transit Station',
        'subway_station': 'Transit Station',
        'metro_station': 'Transit Station',
        'transit_station': 'Transit Station',

        # Office/Business
        'office_building': 'Office Building',
        'business_center': 'Office Building',
        'corporate_campus': 'Office Building',

        # Other
        'food_court': 'Food Court',
        'market': 'Market',
        'supermarket': 'Market',
        'grocery_store': 'Market',
    }

    def __init__(self):
        """Initialize EstablishmentTransformer"""
        pass

    # ========================================================================
    # Inside Establishment Detection
    # ========================================================================

    @staticmethod
    def detect_inside_establishment(inside_places: Any) -> str:
        """
        Detect if POI is inside another establishment

        Args:
            inside_places: Raw inside_places field

        Returns:
            'yes' if inside another establishment, 'no' otherwise
        """
        if pd.isna(inside_places):
            return 'no'

        inside_str = str(inside_places).strip()

        # Empty or null-like values
        if not inside_str or inside_str.lower() in ['', 'nan', 'none', 'null', '[]', '{}']:
            return 'no'

        return 'yes'

    # ========================================================================
    # Parent Establishment Name
    # ========================================================================

    @staticmethod
    def extract_parent_name(inside_places: Any) -> Optional[str]:
        """
        Extract parent establishment name

        Args:
            inside_places: Raw inside_places field (may be comma-separated list)

        Returns:
            Primary parent establishment name or None
        """
        if pd.isna(inside_places):
            return None

        inside_str = str(inside_places).strip()

        # Empty or null-like values
        if not inside_str or inside_str.lower() in ['', 'nan', 'none', 'null', '[]', '{}']:
            return None

        # If comma-separated, take the first one
        if ',' in inside_str:
            names = [n.strip() for n in inside_str.split(',') if n.strip()]
            return names[0] if names else None

        return inside_str

    # ========================================================================
    # Parent Establishment Type
    # ========================================================================

    def extract_parent_type(self, inside_places_categories: Any) -> Optional[str]:
        """
        Extract parent establishment type from categories

        Args:
            inside_places_categories: Raw categories of parent establishments

        Returns:
            Mapped parent type (Mall, Airport, etc.) or None
        """
        if pd.isna(inside_places_categories):
            return None

        cat_str = str(inside_places_categories).strip().lower()

        # Empty or null-like values
        if not cat_str or cat_str in ['', 'nan', 'none', 'null', '[]', '{}']:
            return None

        # Check against mapping
        for keyword, parent_type in self.PARENT_TYPE_MAPPING.items():
            if keyword in cat_str:
                return parent_type

        # Try to infer from common patterns
        if 'mall' in cat_str or 'shopping' in cat_str:
            return 'Mall'
        if 'airport' in cat_str or 'terminal' in cat_str:
            return 'Airport'
        if 'hospital' in cat_str or 'medical' in cat_str:
            return 'Hospital'
        if 'university' in cat_str or 'college' in cat_str or 'school' in cat_str:
            return 'Campus'
        if 'hotel' in cat_str or 'resort' in cat_str:
            return 'Hotel'
        if 'station' in cat_str:
            return 'Transit Station'
        if 'stadium' in cat_str or 'arena' in cat_str:
            return 'Stadium'

        return 'Other'

    # ========================================================================
    # Floor Level Processing
    # ========================================================================

    @staticmethod
    def normalize_floor_level(floor_no: Any) -> Optional[str]:
        """
        Normalize floor level to standard format

        Args:
            floor_no: Raw floor number

        Returns:
            Normalized floor level (e.g., "L2", "Ground", "B1") or None
        """
        if pd.isna(floor_no):
            return None

        floor_str = str(floor_no).strip()

        # Empty values
        if not floor_str or floor_str.lower() in ['', 'nan', 'none', 'null']:
            return None

        # Already has level prefix
        if floor_str.upper().startswith('L') or floor_str.upper().startswith('B'):
            return floor_str.upper()

        # Ground floor patterns
        if floor_str.lower() in ['ground', 'g', 'ground floor', 'lobby', '0']:
            return 'Ground'

        # Basement patterns
        if 'basement' in floor_str.lower() or floor_str.startswith('-'):
            num = re.search(r'\d+', floor_str)
            if num:
                return f'B{num.group()}'
            return 'B1'

        # Numeric floors
        if floor_str.isdigit():
            num = int(floor_str)
            if num == 0:
                return 'Ground'
            elif num > 0:
                return f'L{num}'
            else:
                return f'B{abs(num)}'

        # Return as-is if can't normalize
        return floor_str

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all establishment transformations to a DataFrame

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with transformed columns
        """
        result = df.copy()

        # Inside establishment flag
        if 'inside_places' in df.columns:
            result['inside_establishment_flag'] = df['inside_places'].apply(
                self.detect_inside_establishment
            )

        # Parent establishment name
        if 'inside_places' in df.columns:
            result['parent_establishment_name'] = df['inside_places'].apply(
                self.extract_parent_name
            )

        # Parent establishment type
        if 'inside_places_categories' in df.columns:
            result['parent_establishment_type'] = df['inside_places_categories'].apply(
                self.extract_parent_type
            )
        elif 'inside_places' in df.columns:
            # Try to infer from name if categories not available
            result['parent_establishment_type'] = None

        # Floor level
        if 'floor_no' in df.columns:
            result['floor_level'] = df['floor_no'].apply(self.normalize_floor_level)

        return result
