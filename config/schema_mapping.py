"""Schema mapping configuration for the POI data pipeline."""

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

# Required columns for input POI data
REQUIRED_INPUT_COLUMNS = ['google_id', 'name', 'latitude', 'longitude']

# Required columns for brand config file
BRAND_CONFIG_COLUMNS = ['name', 'website_domain', 'brand_name']

# Required columns for category mapping file
CATEGORY_MAPPING_COLUMNS = ['original_category', 'meta_category', 'middle_category', 'target_category']

DIRECT_MAPPINGS = {
    'name': 'name',
    'latitude': 'latitude',
    'longitude': 'longitude',
    'address_full': 'address',
    'street': 'street',
    'locality': 'locality',
    'region': 'region_level_1',
    'postal_code': 'postcode',
    'country_code': 'country',
    'country_isocode': 'country',
    'rating_count': 'rating_count',
    'average_rating': 'rating',
    'hotel_star_rating': 'hotel_stars',
    'floor_level': 'floor_no',
    'open_hours': 'open_hours',
    'website_domain': 'website_domain',
    'phone': 'phone',
    'description': 'description',
}

TARGET_SCHEMA = {
    'poi_id': {'type': 'str', 'source': 'google_id', 'transform': 'hash_md5'},
    'name': {'type': 'str', 'source': 'name', 'transform': None},
    'chain_flag': {'type': 'str', 'source': None, 'transform': 'detect_chain'},
    'brand_name': {'type': 'str', 'source': None, 'transform': 'match_brand'},
    'category_level_1': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l1'},
    'category_level_2': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l2'},
    'category_level_3': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l3'},
    'category_level_4': {'type': 'str', 'source': 'category_main', 'transform': 'map_category_l4'},
    'status': {'type': 'str', 'source': 'business_status', 'transform': 'normalize_status'},
    'latitude': {'type': 'float', 'source': 'latitude', 'transform': 'add_noise'},
    'longitude': {'type': 'float', 'source': 'longitude', 'transform': 'add_noise'},
    'address_full': {'type': 'str', 'source': 'address', 'transform': 'clean_address'},
    'street': {'type': 'str', 'source': 'street', 'transform': None},
    'locality': {'type': 'str', 'source': 'locality', 'transform': None},
    'region': {'type': 'str', 'source': 'region_level_1', 'transform': None},
    'postal_code': {'type': 'str', 'source': 'postcode', 'transform': 'validate_postcode'},
    'country_code': {'type': 'str', 'source': 'country', 'transform': None},
    'country_isocode': {'type': 'str', 'source': 'country', 'transform': None},
    'inside_establishment_flag': {'type': 'str', 'source': 'inside_places', 'transform': 'detect_inside'},
    'parent_establishment_name': {'type': 'str', 'source': 'inside_places', 'transform': 'extract_parent_name'},
    'parent_establishment_type': {'type': 'str', 'source': 'inside_places_categories', 'transform': 'extract_parent_type'},
    'floor_level': {'type': 'str', 'source': 'floor_no', 'transform': None},
    'status_change': {'type': 'str', 'source': None, 'transform': 'track_status_change'},
    'open_date': {'type': 'str', 'source': 'oldest_date', 'transform': 'parse_open_date'},
    'closed_date': {'type': 'str', 'source': None, 'transform': 'track_closed_date'},
    'last_verified_date': {'type': 'str', 'source': 'day_time', 'transform': 'parse_date'},
    'dining_type': {'type': 'str', 'source': None, 'transform': 'classify_dining'},
    'price_level': {'type': 'int', 'source': 'price_level', 'transform': 'standardize_price'},
    'average_stay_duration_minutes': {'type': 'int', 'source': 'time_spent', 'transform': 'parse_duration'},
    'traffic_score': {'type': 'float', 'source': 'popular_times_data', 'transform': 'calculate_traffic'},
    'rating_count': {'type': 'int', 'source': 'rating_count', 'transform': None},
    'review_count': {'type': 'int', 'source': 'reviews', 'transform': 'extract_review_count'},
    'average_rating': {'type': 'float', 'source': 'rating', 'transform': None},
    'data_version_month': {'type': 'str', 'source': None, 'transform': 'from_filename'},
    'verification_confidence_score': {'type': 'int', 'source': None, 'transform': 'calculate_confidence'},
    'data_quality_flag': {'type': 'str', 'source': None, 'transform': 'assess_quality'},
    'hotel_star_rating': {'type': 'int', 'source': 'hotel_stars', 'transform': None},
}

FINAL_OUTPUT_COLUMNS = [
    'poi_id', 'name', 'chain_flag', 'brand_name',
    'category_level_1', 'category_level_2', 'category_level_3', 'category_level_4',
    'status',
    'latitude', 'longitude', 'address_full', 'street', 'locality', 'region',
    'postal_code', 'country_code', 'country_isocode',
    'inside_establishment_flag', 'parent_establishment_name',
    'parent_establishment_type', 'floor_level',
    'status_change', 'open_date', 'closed_date', 'last_verified_date',
    'dining_type', 'price_level',
    'average_stay_duration_minutes', 'traffic_score',
    'rating_count', 'review_count', 'average_rating',
    'data_version_month',
    'hotel_star_rating',
    'website_domain', 'phone', 'open_hours',
]

STATUS_MAPPING = {
    'open': 'Open',
    'open 24 hours': 'Open',
    'permanently closed': 'Closed',
    'temporarily closed': 'Temporarily Closed',
}

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

RESTAURANT_KEYWORDS = [
    'restaurant', 'food', 'dining', 'cafe', 'deli', 'grill',
    'kitchen', 'eatery', 'bistro', 'brasserie', 'cafeteria',
    'chicken', 'seafood', 'pizza', 'burger', 'sandwich', 'taco',
    'bar', 'steakhouse', 'sushi', 'bakery', 'coffee', 'juice',
    'eateries', 'food court'
]

RESTAURANT_LEVEL2_CATEGORIES = [
    'Restaurants & Eateries',
    'Food & Dining Establishments',
    'Food Court',
    'Cafes & Coffee Shops',
    'Bars & Nightlife',
]

QSR_BRAND_KEYWORDS = [
    'subway', 'pizza hut', 'burger king', 'starbucks', 'smoothie king',
    'popeyes', 'chick-fil-a', 'dairy queen', 'papa johns', 'taco bell',
    'wendy', 'mcdonald', 'kfc', 'arby', 'dunkin', 'chipotle', 'panera',
    'five guys', 'in-n-out', 'sonic', 'jack in the box', 'whataburger',
    'del taco', 'carl\'s jr', 'hardee', 'wingstop', 'jersey mike',
    'firehouse subs', 'jimmy john', 'qdoba', 'moe\'s', 'raising cane'
]

DINING_TYPE_THRESHOLDS = {
    'QSR': 5,
    'Fine Dining': 7,
    'Family Dining': 6,
    'Casual Dining': 4,
}
