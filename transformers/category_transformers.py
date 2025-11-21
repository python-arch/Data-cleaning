"""Category transformations for hierarchical mapping and dining classification."""

import pandas as pd
import numpy as np
import re
from typing import Optional, Dict, Any, List
from ast import literal_eval


class CategoryTransformer:
    """Handles category hierarchy mapping and dining type classification."""

    RESTAURANT_KEYWORDS = [
        'restaurant', 'food', 'dining', 'cafe', 'deli', 'grill',
        'kitchen', 'eatery', 'bistro', 'brasserie', 'cafeteria',
        'chicken', 'seafood', 'pizza', 'burger', 'sandwich', 'taco',
        'bar', 'steakhouse', 'sushi', 'bakery', 'coffee', 'juice'
    ]

    QSR_BRANDS = [
        'subway', 'pizza hut', 'burger king', 'starbucks', 'smoothie king',
        'popeyes', 'chick-fil-a', 'dairy queen', 'papa johns', 'taco bell',
        'wendy', 'mcdonald', 'kfc', 'arby', 'dunkin', 'chipotle', 'panera',
        'five guys', 'in-n-out', 'sonic', 'jack in the box', 'whataburger',
        'del taco', 'carl\'s jr', 'hardee', 'wingstop', 'jersey mike',
        'firehouse subs', 'jimmy john', 'qdoba', 'moe\'s', 'raising cane'
    ]

    LEVEL1_COLUMNS = ['meta_category', 'big_category', 'category_level_1', 'category_l1']
    LEVEL2_COLUMNS = ['middle_category', 'mapped_category', 'category_level_2', 'category_l2']
    LEVEL3_COLUMNS = ['target_category', 'final_category', 'category_level_3', 'category_l3']
    ORIGINAL_COLUMNS = ['original_category', 'source_category', 'category', 'category_main']

    def __init__(self, category_mapping_df: Optional[pd.DataFrame] = None):
        self.category_mapping = category_mapping_df
        self._column_mapping = {}
        self._build_category_index()

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find the first matching column name from candidates."""
        if df is None:
            return None
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def _build_category_index(self):
        """Build lookup index for category mapping."""
        self.category_map = {}

        if self.category_mapping is None:
            return

        # Detect column names
        original_col = self._find_column(self.category_mapping, self.ORIGINAL_COLUMNS)
        level1_col = self._find_column(self.category_mapping, self.LEVEL1_COLUMNS)
        level2_col = self._find_column(self.category_mapping, self.LEVEL2_COLUMNS)
        level3_col = self._find_column(self.category_mapping, self.LEVEL3_COLUMNS)

        # Store mapping for reference
        self._column_mapping = {
            'original': original_col,
            'level_1': level1_col,
            'level_2': level2_col,
            'level_3': level3_col,
        }

        if original_col is None:
            # No original category column found, cannot build mapping
            return

        for _, row in self.category_mapping.iterrows():
            try:
                original = row.get(original_col)
                if pd.isna(original):
                    continue

                original = str(original).lower().strip()
                if not original:
                    continue

                # Get category levels, handling missing columns gracefully
                level_1 = None
                level_2 = None
                level_3 = None

                if level1_col and pd.notna(row.get(level1_col)):
                    level_1 = str(row.get(level1_col)).strip()
                    if not level_1:
                        level_1 = None

                if level2_col and pd.notna(row.get(level2_col)):
                    level_2 = str(row.get(level2_col)).strip()
                    if not level_2:
                        level_2 = None

                if level3_col and pd.notna(row.get(level3_col)):
                    level_3 = str(row.get(level3_col)).strip()
                    if not level_3:
                        level_3 = None

                self.category_map[original] = {
                    'level_1': level_1,
                    'level_2': level_2,
                    'level_3': level_3,
                }

            except Exception:
                continue

    def map_category(self, category_main: Any) -> Dict[str, Optional[str]]:
        """Map original category to hierarchical levels."""
        if pd.isna(category_main):
            return {'level_1': None, 'level_2': None, 'level_3': None}

        key = str(category_main).lower().strip()

        if key in self.category_map:
            return self.category_map[key]

        return {'level_1': None, 'level_2': None, 'level_3': None}

    def transform_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply category mapping to DataFrame."""
        result = df.copy()

        if 'category_main' in df.columns:
            mapped = df['category_main'].apply(self.map_category)
            result['category_level_1'] = mapped.apply(lambda x: x['level_1'])
            result['category_level_2'] = mapped.apply(lambda x: x['level_2'])
            result['category_level_3'] = mapped.apply(lambda x: x['level_3'])

        return result

    @staticmethod
    def safe_eval(val: Any) -> Dict:
        """Safely evaluate string dicts."""
        if pd.isna(val) or val == '':
            return {}
        try:
            return literal_eval(val)
        except:
            return {}

    def _is_restaurant(self, category_main: str, categories_list: str,
                       category_level_2: Optional[str] = None) -> bool:
        """Check if POI is a restaurant based on categories."""
        if category_level_2 and pd.notna(category_level_2):
            level2_lower = str(category_level_2).lower().strip()
            if 'restaurant' in level2_lower or 'eateries' in level2_lower or \
               'dining' in level2_lower or 'food' in level2_lower:
                return True

        # Check original category
        category_lower = str(category_main).lower() if pd.notna(category_main) else ''
        categories_lower = str(categories_list).lower() if pd.notna(categories_list) else ''

        return any(keyword in category_lower or keyword in categories_lower
                   for keyword in self.RESTAURANT_KEYWORDS)

    def classify_dining_type(self, row: pd.Series) -> Optional[str]:
        """Classify restaurant into dining categories."""
        category_main = str(row.get('category_main', '')).lower() if pd.notna(row.get('category_main')) else ''
        categories_list = str(row.get('categories_list', '')).lower() if pd.notna(row.get('categories_list')) else ''
        name = str(row.get('name', '')).lower() if pd.notna(row.get('name')) else ''

        price_level = row.get('price_level')
        if pd.isna(price_level):
            price_level = None
        else:
            try:
                price_level = int(price_level)
            except (TypeError, ValueError):
                price_level = None

        category_level_2 = row.get('category_level_2')

        if not self._is_restaurant(category_main, categories_list, category_level_2):
            return None

        describe_data_raw = row.get('describe_data', '{}')
        if pd.isna(describe_data_raw):
            describe_data = {}
        else:
            describe_data = self.safe_eval(describe_data_raw)
            if not isinstance(describe_data, dict):
                describe_data = {}

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

        casual_score = 0
        if any('casual' in a for a in atmosphere_values):
            casual_score += 4
        if 'serves dine-in' in str(service_values):
            casual_score += 2
        if price_level in [2, 3]:
            casual_score += 2

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
            if price_level == 1:
                return 'QSR'
            elif price_level in [4, 5]:
                return 'Fine Dining'
            elif price_level == 2:
                return 'Family Dining'
            else:
                return 'Casual Dining'

        for category, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if score == max_score:
                return category

        return 'Casual Dining'

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all category transformations to a DataFrame."""
        result = self.transform_categories(df)
        result['dining_type'] = result.apply(self.classify_dining_type, axis=1)
        return result
