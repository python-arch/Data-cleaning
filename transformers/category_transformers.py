"""Category transformations for hierarchical mapping and dining classification."""

import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from ast import literal_eval

logger = logging.getLogger(__name__)


class CategoryTransformer:
    """Handles category hierarchy mapping and dining type classification."""

    REQUIRED_MAPPING_COLUMNS = ['original_category', 'meta_category', 'middle_category', 'target_category']

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

    def __init__(self, category_mapping_df: Optional[pd.DataFrame] = None):
        self.category_mapping = category_mapping_df
        self._validate_mapping()
        self._build_category_index()

    def _validate_mapping(self):
        """Validate category mapping has required columns."""
        if self.category_mapping is None:
            logger.info("No category mapping provided, categories will be empty")
            return

        missing = [c for c in self.REQUIRED_MAPPING_COLUMNS if c not in self.category_mapping.columns]
        if missing:
            raise ValueError(f"Category mapping missing required columns: {missing}. "
                           f"Expected: {self.REQUIRED_MAPPING_COLUMNS}")

        logger.info(f"Category mapping validated: {len(self.category_mapping)} entries")

    def _build_category_index(self):
        """Build lookup index for category mapping."""
        self.category_map = {}

        if self.category_mapping is None:
            return

        for _, row in self.category_mapping.iterrows():
            try:
                original = row['original_category']
                if pd.isna(original):
                    continue

                original = str(original).lower().strip()
                if not original:
                    continue

                # Mapping:
                # meta_category -> category_level_1
                # middle_category -> category_level_2
                # target_category -> category_level_3
                # category_main (original_category) -> category_level_4
                level_1 = self._get_value(row, 'meta_category')
                level_2 = self._get_value(row, 'middle_category')
                level_3 = self._get_value(row, 'target_category')
                level_4 = self._get_value(row, 'original_category')

                self.category_map[original] = {
                    'level_1': level_1,
                    'level_2': level_2,
                    'level_3': level_3,
                    'level_4': level_4,
                }

            except Exception as e:
                logger.debug(f"Skipping malformed category row: {e}")
                continue

        logger.info(f"Category index built: {len(self.category_map)} mappings")

    def _get_value(self, row: pd.Series, col: str) -> Optional[str]:
        val = row.get(col)
        if pd.isna(val):
            return None
        val = str(val).strip()
        return val if val else None

    def map_category(self, category_main: Any) -> Dict[str, Optional[str]]:
        """Map original category to hierarchical levels."""
        if pd.isna(category_main):
            return {'level_1': None, 'level_2': None, 'level_3': None, 'level_4': None}

        key = str(category_main).lower().strip()
        if key in self.category_map:
            return self.category_map[key]

        return {'level_1': None, 'level_2': None, 'level_3': None, 'level_4': None}

    def transform_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply category mapping to DataFrame."""
        result = df.copy()

        if 'category_main' not in df.columns:
            logger.warning("Missing category_main column, skipping category mapping")
            result['category_level_1'] = None
            result['category_level_2'] = None
            result['category_level_3'] = None
            result['category_level_4'] = None
            return result

        mapped = df['category_main'].apply(self.map_category)
        result['category_level_1'] = mapped.apply(lambda x: x['level_1'])
        result['category_level_2'] = mapped.apply(lambda x: x['level_2'])
        result['category_level_3'] = mapped.apply(lambda x: x['level_3'])
        result['category_level_4'] = mapped.apply(lambda x: x['level_4'])

        return result

    @staticmethod
    def safe_eval(val: Any) -> Dict:
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
