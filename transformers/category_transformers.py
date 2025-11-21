"""
Category Transformers - Hierarchical Category Mapping
"""

import pandas as pd
import numpy as np
import re
from typing import Optional, Dict, Any, List
from ast import literal_eval


class CategoryTransformer:
    """
    Handles category-related transformations:
    - category_level_1/2/3: Hierarchical business categories
    - dining_type: QSR, Casual Dining, Fine Dining, Family Dining
    """

    # Restaurant keywords for classification
    RESTAURANT_KEYWORDS = [
        'restaurant', 'food', 'dining', 'cafe', 'deli', 'grill',
        'kitchen', 'eatery', 'bistro', 'brasserie', 'cafeteria',
        'chicken', 'seafood', 'pizza', 'burger', 'sandwich', 'taco',
        'bar', 'steakhouse', 'sushi', 'bakery', 'coffee', 'juice'
    ]

    # QSR brand keywords
    QSR_BRANDS = [
        'subway', 'pizza hut', 'burger king', 'starbucks', 'smoothie king',
        'popeyes', 'chick-fil-a', 'dairy queen', 'papa johns', 'taco bell',
        'wendy', 'mcdonald', 'kfc', 'arby', 'dunkin', 'chipotle', 'panera',
        'five guys', 'in-n-out', 'sonic', 'jack in the box', 'whataburger',
        'del taco', 'carl\'s jr', 'hardee', 'wingstop', 'jersey mike',
        'firehouse subs', 'jimmy john', 'qdoba', 'moe\'s', 'raising cane'
    ]

    def __init__(self, category_mapping_df: Optional[pd.DataFrame] = None):
        """
        Initialize CategoryTransformer

        Args:
            category_mapping_df: DataFrame with category mapping
                Expected columns: original_category, target_category, middle_category, meta_category
        """
        self.category_mapping = category_mapping_df
        self._build_category_index()

    def _build_category_index(self):
        """Build efficient lookup for category mapping"""
        self.category_map = {}

        if self.category_mapping is not None:
            for _, row in self.category_mapping.iterrows():
                original = str(row.get('original_category', '')).lower().strip()
                if original:
                    self.category_map[original] = {
                        'level_1': row.get('meta_category'),
                        'level_2': row.get('middle_category'),
                        'level_3': row.get('target_category'),
                    }

    # ========================================================================
    # Category Mapping
    # ========================================================================

    def map_category(self, category_main: Any) -> Dict[str, Optional[str]]:
        """
        Map original category to hierarchical levels

        Args:
            category_main: Original category string

        Returns:
            Dict with level_1, level_2, level_3
        """
        if pd.isna(category_main):
            return {'level_1': None, 'level_2': None, 'level_3': None}

        key = str(category_main).lower().strip()

        if key in self.category_map:
            return self.category_map[key]

        return {'level_1': None, 'level_2': None, 'level_3': None}

    def transform_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply category mapping to DataFrame

        Args:
            df: DataFrame with category_main column

        Returns:
            DataFrame with category_level_1/2/3 columns
        """
        result = df.copy()

        if 'category_main' in df.columns:
            mapped = df['category_main'].apply(self.map_category)
            result['category_level_1'] = mapped.apply(lambda x: x['level_1'])
            result['category_level_2'] = mapped.apply(lambda x: x['level_2'])
            result['category_level_3'] = mapped.apply(lambda x: x['level_3'])

        return result

    # ========================================================================
    # Dining Type Classification
    # ========================================================================

    @staticmethod
    def safe_eval(val: Any) -> Dict:
        """Safely evaluate string representations of dictionaries"""
        if pd.isna(val) or val == '':
            return {}
        try:
            return literal_eval(val)
        except:
            return {}

    def _is_restaurant(self, category_main: str, categories_list: str) -> bool:
        """Check if POI is a restaurant based on categories"""
        category_lower = str(category_main).lower() if pd.notna(category_main) else ''
        categories_lower = str(categories_list).lower() if pd.notna(categories_list) else ''

        return any(keyword in category_lower or keyword in categories_lower
                   for keyword in self.RESTAURANT_KEYWORDS)

    def classify_dining_type(self, row: pd.Series) -> Optional[str]:
        """
        Classify restaurant into dining categories

        Args:
            row: DataFrame row with relevant columns

        Returns:
            Dining type: QSR, Fine Dining, Family Dining, Casual Dining, or None
        """
        category_main = str(row.get('category_main', '')).lower()
        categories_list = str(row.get('categories_list', '')).lower()
        name = str(row.get('name', '')).lower()
        price_level = row.get('price_level')

        # Check if it's a restaurant
        if not self._is_restaurant(category_main, categories_list):
            return None

        # Parse describe_data
        describe_data_raw = row.get('describe_data', '{}')
        if pd.isna(describe_data_raw):
            describe_data = {}
        else:
            describe_data = self.safe_eval(describe_data_raw)
            if not isinstance(describe_data, dict):
                describe_data = {}

        # Extract data safely
        atmosphere = describe_data.get('atmosphere', {}) or {}
        offerings = describe_data.get('offerings', {}) or {}
        service_options = describe_data.get('service_options', {}) or {}
        dining_options = describe_data.get('dining_options', {}) or {}
        crowd = describe_data.get('crowd', {}) or {}
        planning = describe_data.get('planning', {}) or {}

        atmosphere_values = [str(v).lower() for v in atmosphere.values()]
        offerings_values = [str(v).lower() for v in offerings.values()]
        service_values = [str(v).lower() for v in service_options.values()]
        crowd_values = [str(v).lower() for v in crowd.values()]
        planning_values = [str(v).lower() for v in planning.values()]

        # Calculate scores
        # QSR Score
        qsr_score = 0
        if any(keyword in name for keyword in self.QSR_BRANDS):
            qsr_score += 5
        if 'fast food' in categories_list or 'fast_food_restaurant' in categories_list:
            qsr_score += 4
        if any('quick bite' in v for v in offerings_values):
            qsr_score += 2
        if any('drive-through' in v or 'counter service' in v for v in service_values):
            qsr_score += 2
        if price_level == 1:
            qsr_score += 2
        if "doesn't accept reservations" in str(planning_values):
            qsr_score += 1

        # Fine Dining Score
        fine_dining_score = 0
        if price_level in [4, 5]:
            fine_dining_score += 5
        elif price_level == 3:
            fine_dining_score += 2
        if any('upscale' in a for a in atmosphere_values):
            fine_dining_score += 4
        if any('serves wine' in o or 'serves cocktails' in o for o in offerings_values):
            fine_dining_score += 2
        if 'accepts reservations' in str(planning_values):
            fine_dining_score += 3

        # Family Dining Score
        family_dining_score = 0
        if any('family-friendly' in c for c in crowd_values):
            family_dining_score += 4
        if any('good for groups' in c for c in crowd_values):
            family_dining_score += 2
        if price_level == 2:
            family_dining_score += 3
        elif price_level == 3:
            family_dining_score += 1
        if any('good for kids' in c for c in crowd_values):
            family_dining_score += 2

        # Casual Dining Score
        casual_score = 0
        if any('casual' in a for a in atmosphere_values):
            casual_score += 4
        if 'serves dine-in' in str(service_values):
            casual_score += 2
        if price_level in [2, 3]:
            casual_score += 2

        # Decision logic
        if qsr_score >= 5:
            return 'QSR'
        if fine_dining_score >= 7:
            return 'Fine Dining'
        if family_dining_score >= 6:
            return 'Family Dining'

        scores = {
            'QSR': qsr_score,
            'Fine Dining': fine_dining_score,
            'Family Dining': family_dining_score,
            'Casual Dining': casual_score
        }

        max_score = max(scores.values())
        if max_score == 0:
            # Fallback based on price level
            if price_level == 1:
                return 'QSR'
            elif price_level in [4, 5]:
                return 'Fine Dining'
            elif price_level == 2:
                return 'Family Dining'
            else:
                return 'Casual Dining'

        # Return highest scoring category
        for category, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if score == max_score:
                return category

        return 'Casual Dining'

    # ========================================================================
    # Batch Transformations
    # ========================================================================

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all category transformations to a DataFrame

        Args:
            df: Input DataFrame

        Returns:
            DataFrame with transformed columns
        """
        result = self.transform_categories(df)

        # Add dining type classification
        result['dining_type'] = df.apply(self.classify_dining_type, axis=1)

        return result
