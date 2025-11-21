"""
Schema Mapping Configuration
Maps source S3 data fields to target output fields
"""

# Source columns from S3 data
SOURCE_COLUMNS = [
    'name', 'name_second', 'country_name', 'country', 'floor_no', 'phone', 'phone_local',
    'street', 'locality', 'sub_locality', 'region_level_1', 'region_level_2', 'postcode',
    'plus_code', 'address', 'latitude', 'longitude', 'rating', 'rating_count',
    'rating_by_star', 'price_range', 'price_reported', 'gas_cost', 'business_status',
    'area_type', 'is_claimed', 'types', 'category_main', 'categories_list', 'description',
    'place_amenities', 'spoken_language', 'link', 'website', 'website_domain',
    'website_contact', 'inside_places', 'inside_places_categories', 'inside_places_ids',
    'open_hours', 'time_spent', 'price_level', 'stopid', 'menu', 'find_table',
    'place_order', 'trip', 'popular_times_data', 'popular_times_data_kg', 'describe_data',
    'zone', 'zone_main', 'timeoffset', 'similarplaces', 'similarplaces_category',
    'similarplaces_ids', 'similarplaces_all', 'booking', 'hotels_url', 'hotel_stars',
    'hotel_price', 'hotel_data', 'check_in', 'check_out', 'id_one', 'id_two', 'id_three',
    'google_review_link', 'sentiments', 'kg_menu', 'reviews', 'day_time', 'photo_link',
    'streetview_date', 'photo_dates', 'review_dates', 'oldest_date', 'logo', 'link_id',
    'google_id'
]

# Direct field mappings: target_field -> source_field
DIRECT_MAPPINGS = {
    'name': 'name',
    'latitude': 'latitude',
    'longitude': 'longitude',
    'address_full': 'address',
    'street': 'street',
    'city': 'locality',
    'state': 'region_level_1',
    'postal_code': 'postcode',
    'country_code': 'country',
    'country_isocode': 'country',
    'review_count': 'rating_count',
    'average_rating': 'rating',
    'hotel_star_rating': 'hotel_stars',
    'floor_level': 'floor_no',
    'open_hours': 'open_hours',
    'website_domain': 'website_domain',
    'phone': 'phone',
    'description': 'description',
}

# Target output schema with all required fields
TARGET_SCHEMA = {
    # Core Identification
    'poi_id': {'type': 'str', 'source': 'google_id', 'transform': 'hash_md5'},
    'name': {'type': 'str', 'source': 'name', 'transform': None},
    'chain_flag': {'type': 'str', 'source': None, 'transform': 'detect_chain'},  # yes/no
    'brand_name': {'type': 'str', 'source': None, 'transform': 'match_brand'},

    # Hierarchical Categories
    'category_level_1': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l1'},
    'category_level_2': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l2'},
    'category_level_3': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l3'},

    # Status
    'status': {'type': 'str', 'source': 'business_status', 'transform': 'normalize_status'},

    # Location - Coordinates
    'latitude': {'type': 'float', 'source': 'latitude', 'transform': 'add_noise'},
    'longitude': {'type': 'float', 'source': 'longitude', 'transform': 'add_noise'},

    # Location - Address
    'address_full': {'type': 'str', 'source': 'address', 'transform': 'clean_address'},
    'street': {'type': 'str', 'source': 'street', 'transform': None},
    'city': {'type': 'str', 'source': 'locality', 'transform': None},
    'state': {'type': 'str', 'source': 'region_level_1', 'transform': None},
    'postal_code': {'type': 'str', 'source': 'postcode', 'transform': 'validate_postcode'},
    'country_code': {'type': 'str', 'source': 'country', 'transform': None},
    'country_isocode': {'type': 'str', 'source': 'country', 'transform': None},

    # Inside Establishment
    'inside_establishment_flag': {'type': 'str', 'source': 'inside_places', 'transform': 'detect_inside'},
    'parent_establishment_name': {'type': 'str', 'source': 'inside_places', 'transform': 'extract_parent_name'},
    'parent_establishment_type': {'type': 'str', 'source': 'inside_places_categories', 'transform': 'extract_parent_type'},
    'floor_level': {'type': 'str', 'source': 'floor_no', 'transform': None},

    # Temporal / Status Change
    'status_change': {'type': 'str', 'source': None, 'transform': 'track_status_change'},
    'open_date': {'type': 'str', 'source': 'oldest_date', 'transform': 'parse_open_date'},
    'closed_date': {'type': 'str', 'source': None, 'transform': 'track_closed_date'},
    'last_verified_date': {'type': 'str', 'source': 'day_time', 'transform': 'parse_date'},

    # Dining & Pricing
    'dining_type': {'type': 'str', 'source': None, 'transform': 'classify_dining'},
    'price_level': {'type': 'int', 'source': 'price_level', 'transform': 'standardize_price'},

    # Traffic & Duration
    'average_stay_duration_minutes': {'type': 'int', 'source': 'time_spent', 'transform': 'parse_duration'},
    'traffic_score': {'type': 'float', 'source': 'popular_times_data', 'transform': 'calculate_traffic'},

    # Reviews
    'review_count': {'type': 'int', 'source': 'rating_count', 'transform': None},
    'average_rating': {'type': 'float', 'source': 'rating', 'transform': None},

    # Data Quality & Versioning
    'data_version_month': {'type': 'str', 'source': None, 'transform': 'from_filename'},
    'verification_source': {'type': 'str', 'source': None, 'transform': 'determine_source'},
    'verification_confidence_score': {'type': 'int', 'source': None, 'transform': 'calculate_confidence'},
    'data_quality_flag': {'type': 'str', 'source': None, 'transform': 'assess_quality'},

    # Hotel Specific
    'hotel_star_rating': {'type': 'int', 'source': 'hotel_stars', 'transform': None},
}

# Final output columns in order
FINAL_OUTPUT_COLUMNS = [
    # Core
    'poi_id',
    'name',
    'chain_flag',
    'brand_name',

    # Categories
    'category_level_1',
    'category_level_2',
    'category_level_3',

    # Status
    'status',

    # Location
    'latitude',
    'longitude',
    'address_full',
    'street',
    'city',
    'state',
    'postal_code',
    'country_code',
    'country_isocode',

    # Inside Establishment
    'inside_establishment_flag',
    'parent_establishment_name',
    'parent_establishment_type',
    'floor_level',

    # Temporal
    'status_change',
    'open_date',
    'closed_date',
    'last_verified_date',

    # Dining & Pricing
    'dining_type',
    'price_level',

    # Traffic & Duration
    'average_stay_duration_minutes',
    'traffic_score',

    # Reviews
    'review_count',
    'average_rating',

    # Data Quality
    'data_version_month',
    'verification_source',
    'verification_confidence_score',
    'data_quality_flag',

    # Hotel
    'hotel_star_rating',

    # Additional metadata
    'website_domain',
    'phone',
    'open_hours',
]

# Status normalization mapping
STATUS_MAPPING = {
    'open': 'Open',
    'open 24 hours': 'Open',
    'operational': 'Open',
    'closed': 'Closed',
    'permanently closed': 'Closed',
    'closed permanently': 'Closed',
    'closed_temporarily': 'Temporarily Closed',
    'temporarily closed': 'Temporarily Closed',
}

# Parent establishment type mapping
PARENT_TYPE_MAPPING = {
    'shopping_mall': 'Mall',
    'mall': 'Mall',
    'airport': 'Airport',
    'hospital': 'Hospital',
    'university': 'Campus',
    'school': 'Campus',
    'hotel': 'Hotel',
    'casino': 'Casino',
    'stadium': 'Stadium',
    'convention_center': 'Convention Center',
    'train_station': 'Transit Station',
    'bus_station': 'Transit Station',
    'subway_station': 'Transit Station',
}

# Restaurant category keywords for detection
RESTAURANT_KEYWORDS = [
    'restaurant', 'food', 'dining', 'cafe', 'deli', 'grill',
    'kitchen', 'eatery', 'bistro', 'brasserie', 'cafeteria',
    'chicken', 'seafood', 'pizza', 'burger', 'sandwich', 'taco',
    'bar', 'steakhouse', 'sushi', 'bakery', 'coffee', 'juice',
    'eateries', 'food court'
]

# Restaurant category level 2 matches (from xmap_poi)
RESTAURANT_LEVEL2_CATEGORIES = [
    'Restaurants & Eateries',
    'Food & Dining Establishments',
    'Food Court',
    'Cafes & Coffee Shops',
    'Bars & Nightlife',
]

# QSR (Quick Service Restaurant) brand keywords
QSR_BRAND_KEYWORDS = [
    'subway', 'pizza hut', 'burger king', 'starbucks', 'smoothie king',
    'popeyes', 'chick-fil-a', 'dairy queen', 'papa johns', 'taco bell',
    'wendy', 'mcdonald', 'kfc', 'arby', 'dunkin', 'chipotle', 'panera',
    'five guys', 'in-n-out', 'sonic', 'jack in the box', 'whataburger',
    'del taco', 'carl\'s jr', 'hardee', 'wingstop', 'jersey mike',
    'firehouse subs', 'jimmy john', 'qdoba', 'moe\'s', 'raising cane'
]

# Dining type classification thresholds
DINING_TYPE_THRESHOLDS = {
    'QSR': 5,
    'Fine Dining': 7,
    'Family Dining': 6,
    'Casual Dining': 4,
}

# Category level column name candidates for flexible schema support
CATEGORY_COLUMN_CANDIDATES = {
    'original': ['original_category', 'source_category', 'category', 'category_main'],
    'level_1': ['meta_category', 'big_category', 'category_level_1', 'category_l1'],
    'level_2': ['middle_category', 'mapped_category', 'category_level_2', 'category_l2'],
    'level_3': ['target_category', 'final_category', 'category_level_3', 'category_l3'],
}

# Brand config column name candidates for flexible schema support
BRAND_COLUMN_CANDIDATES = {
    'name': ['name', 'poi_name', 'business_name', 'place_name'],
    'domain': ['website_domain', 'domain', 'website', 'web_domain'],
    'brand': ['brand_name', 'brand', 'chain_name', 'parent_brand'],
    'category': ['original_category', 'category', 'user_category', 'category_main'],
}
