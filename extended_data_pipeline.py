from google.colab import drive
drive.mount('/content/drive',force_remount=True)


import pandas as pd
import boto3
import os
import io
import zipfile
import os
from dotenv import load_dotenv
from pathlib import Path 

env_path = Path(".env")
if not env_path.exists():
    raise RuntimeError(".env not found — run ./setup.sh and provide passphrase")

load_dotenv(dotenv_path=env_path)

aws_access_key_id = os.getenv("aws_access_key_id")
aws_secret_access_key = os.getenv("aws_secret_access_key")
aws_region_name = os.getenv("aws_region_name")
s3_bucket_name =  os.getenv("s3_bucket_name")


# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=aws_region_name
)

"""# Data Cleaning"""

import os
import pandas as pd
import boto3
import numpy as np
import json
import phonenumbers
import re
import requests
import time
from hashlib import md5
from datetime import datetime
from openai import AzureOpenAI
from tqdm import tqdm
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing as mp

warnings.filterwarnings("ignore")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Azure OpenAI (Update with your credentials)
client = AzureOpenAI(
    api_key=os.getenv("api_key"),
    api_version=os.getenv("api_version"),
    azure_endpoint=os.getenv("azure_endpoint"),
)

# Google Geocoding API (Update with your key)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEOCODE_DELAY = 0.1  # 100ms delay between requests

# ============================================================================
# OPTIMIZED HELPER FUNCTIONS
# ============================================================================

from ast import literal_eval

def extract_month_from_filename(filename):
        """
        Extract YYYY-MM from YYYYMMDD.csv

        Args:
            filename: e.g., "United States/20250509/United States.zip"

        Returns:
            String in format "YYYY-MM" or None
        """
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            year = date_str[:4]
            month = date_str[4:6]
            return f"{year}-{month}"
        return None

def classify_price_level(price_str):
    """
    Classify Google Maps price levels into 5 standardized levels (1-5).

    Handles:
    - Dollar signs: $, $$, $$$, $$$$
    - Numeric ranges: $1–10, $10–20, $20–30, etc.
    - Edge cases: null, empty, mixed formats

    Returns: int (1-5) or None for invalid/missing values
    """
    # Handle null/empty values
    if pd.isna(price_str) or price_str == '' or price_str is None:
        return None

    # Convert to string and clean
    price_str = str(price_str).strip()

    # Pattern 1: Dollar signs only ($, $$, $$$, $$$$)
    if re.match(r'^\$+$', price_str):
        dollar_count = price_str.count('$')
        if dollar_count == 1:
            return 1
        elif dollar_count == 2:
            return 2
        elif dollar_count == 3:
            return 4
        elif dollar_count >= 4:
            return 5

    # Pattern 2: Numeric ranges ($X–Y, $X-Y, $X+)
    # Extract numeric values
    numbers = re.findall(r'\d+', price_str)

    if numbers:
        if len(numbers) >= 2:
            # Range format: calculate average
            avg_price = (int(numbers[0]) + int(numbers[1])) / 2
        else:
            # Single number or $X+ format: use that number
            avg_price = int(numbers[0])

        # Classification based on average price
        if avg_price < 15:
            return 1
        elif avg_price < 25:
            return 2
        elif avg_price < 40:
            return 3
        elif avg_price < 75:
            return 4
        else:
            return 5

    # Edge case: unrecognized format
    return None

def safe_eval(val):
    """Safely evaluate string representations of dictionaries"""
    if pd.isna(val) or val == '':
        return {}
    try:
        return literal_eval(val)
    except:
        return {}

def get_dining_category(row):
    """Classify restaurant into dining categories"""
    price_level = row.get('price_level', None)
    category_main = str(row.get('category_main', '')).lower()
    categories_list = str(row.get('categories_list', '')).lower()
    name = str(row.get('name', '')).lower()

    # FIX: Handle describe_data more robustly
    describe_data_raw = row.get('describe_data', '{}')

    # Check if it's NaN or None first
    if pd.isna(describe_data_raw):
        describe_data = {}
    else:
        describe_data = safe_eval(describe_data_raw)
        # Double-check it's a dict after safe_eval
        if not isinstance(describe_data, dict):
            describe_data = {}

    # Check if it's a restaurant
    restaurant_keywords = ['restaurant', 'food', 'dining', 'cafe', 'deli', 'grill',
                          'kitchen', 'eatery', 'bistro', 'brasserie', 'cafeteria',
                          'chicken', 'seafood', 'pizza', 'burger', 'sandwich', 'taco',
                          'bar', 'steakhouse', 'sushi', 'bakery', 'coffee', 'juice']

    is_restaurant = any(keyword in category_main or keyword in categories_list
                       for keyword in restaurant_keywords)

    if not is_restaurant:
        return None

    # Extract data from describe_data (safely with .get() and defaults)
    atmosphere = describe_data.get('atmosphere', {})
    offerings = describe_data.get('offerings', {})
    service_options = describe_data.get('service_options', {})
    dining_options = describe_data.get('dining_options', {})
    crowd = describe_data.get('crowd', {})
    planning = describe_data.get('planning', {})
    amenities_data = describe_data.get('amenities', {})

    # Ensure each is a dict before calling .values()
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    offerings = offerings if isinstance(offerings, dict) else {}
    service_options = service_options if isinstance(service_options, dict) else {}
    dining_options = dining_options if isinstance(dining_options, dict) else {}
    crowd = crowd if isinstance(crowd, dict) else {}
    planning = planning if isinstance(planning, dict) else {}

    atmosphere_values = [str(v).lower() for v in atmosphere.values()]
    offerings_values = [str(v).lower() for v in offerings.values()]
    service_values = [str(v).lower() for v in service_options.values()]
    dining_values = [str(v).lower() for v in dining_options.values()]
    crowd_values = [str(v).lower() for v in crowd.values()]
    planning_values = [str(v).lower() for v in planning.values()]

    # QSR Score
    qsr_keywords = ['subway', 'pizza hut', 'burger king', 'starbucks', 'smoothie king',
                    'popeyes', 'chick-fil-a', 'dairy queen', 'papa johns', 'taco bell',
                    'wendy', 'mcdonald', 'kfc', 'arby', 'dunkin', 'chipotle', 'panera']
    qsr_score = 0

    if any(keyword in name for keyword in qsr_keywords):
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

def hash_poi_id(text):
    """Generates an MD5 hash of the text."""
    if pd.isna(text):
        return None
    return md5(str(text).encode('utf-8')).hexdigest()

def get_traffic(traffic_str):
    if pd.isna(traffic_str):
        return None
    try:
        traffic_data = json.loads(traffic_str.replace("'", "\""))
        if isinstance(traffic_data, dict) and 'popular_times' in traffic_data:
            daily_avgs = [day.get('avg') for day in traffic_data['popular_times'] if 'avg' in day]
            if not daily_avgs:
                return None
            return round(sum(daily_avgs) / len(daily_avgs), 2)
        elif isinstance(traffic_data, dict):
            valid_days_scores = []
            for day in traffic_data.keys():
                if isinstance(traffic_data[day], list) and len(traffic_data[day]) >= 3:
                    valid_days_scores.append(traffic_data[day][-3].get('average_popularity'))
            valid_days_scores = [v for v in valid_days_scores if v is not None]
            if not valid_days_scores:
                return None
            return round(sum(valid_days_scores) / len(valid_days_scores), 2)
        return None
    except Exception:
        return None

def validate_single_phone(number):
    """Validates phone number format."""
    if pd.isna(number) or str(number).strip() == '':
        return np.nan
    try:
        cleaned_number = ' '.join(str(number).split())
        parsed_number = phonenumbers.parse(cleaned_number, None)
        return number if phonenumbers.is_valid_number(parsed_number) else np.nan
    except:
        return np.nan

def clean_address(address):
    """Cleans the address string by removing the first component if it contains '+'."""
    if pd.isna(address) or not isinstance(address, str):
        return address
    return ', '.join(address.split(', ')[1:]) if '+' in address else address

def add_random_digits(value):
    """Adds two random digits after the 6th decimal place of a float value."""
    if pd.isna(value):
        return value
    try:
        str_value = str(value)
        if 'e' in str_value.lower() or not (str_value.replace('.', '', 1).replace('-', '', 1).lstrip('+').isdigit()):
            return value
        random_digits = np.random.randint(10, 99)
        if "." in str_value:
            int_part, dec_part = str_value.split(".")
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

def clean_region_with_gadm(df, gadm_boundaries):
    import geopandas as gpd
    gdf = gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df.longitude, df.latitude),
        crs="EPSG:4326",
    )

    # Perform spatial join with GADM boundaries
    gdf = gpd.sjoin(gdf, gadm_boundaries, predicate="within")

    # Update region and locality with GADM data
    if "region" in gdf.columns:
        gdf.rename(columns={"region": "old_region"}, inplace=True)
    if "locality" in gdf.columns:
        gdf.rename(columns={"locality": "old_locality"}, inplace=True)

    gdf.rename(columns={"NAME_1": "region", "NAME_2": "locality"}, inplace=True)

    # Clean up columns
    columns_to_drop = ["old_region", "old_locality", "index_right", "geometry"]
    gdf.drop(columns=[col for col in columns_to_drop if col in gdf.columns], inplace=True)

    return pd.DataFrame(gdf)

# ============================================================================
# VECTORIZED CLEANING FUNCTIONS
# ============================================================================

def extract_postcode_vectorized(addresses):
    """Vectorized postcode extraction"""
    def extract_single(address):
        if pd.isna(address):
            return None
        matches = re.findall(r'\b\d{5}(?:-\d{4})?\b', str(address))
        return matches[-1] if matches else None
    return addresses.apply(extract_single)

def is_valid_us_postcode_vectorized(postcodes):
    """Vectorized postcode validation"""
    def is_valid(postcode):
        if pd.isna(postcode):
            return False
        return bool(re.match(r'^\d{5}(?:-\d{4})?$', str(postcode).strip()))
    return postcodes.apply(is_valid)

def is_outside_usa_vectorized(lats, lons):
    """Vectorized USA boundary check"""
    usa_lat_min, usa_lat_max = 24.0, 49.5
    usa_lon_min, usa_lon_max = -125.0, -66.0

    return (lats.isna() | lons.isna() |
            (lats < usa_lat_min) | (lats > usa_lat_max) |
            (lons < usa_lon_min) | (lons > usa_lon_max))

def is_meaningless_name_vectorized(names):
    """Vectorized meaningless name detection"""
    def is_meaningless(name):
        if pd.isna(name):
            return True
        name_str = str(name).strip()
        if not name_str:
            return True
        if re.match(r'^\d+$', name_str):
            return True
        if re.match(r'^\d+\s*/\s*\d+$', name_str):
            return True
        if re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', name_str):
            return True
        if re.search(r'\b\w+\s+\d+\s*\(\s*\d+/\d+\s*\)', name_str, re.IGNORECASE):
            return True
        meaningful_chars = re.sub(r'[^\w]', '', name_str)
        if not meaningful_chars:
            return True
        if len(set(meaningful_chars)) == 1 and len(meaningful_chars) > 2:
            return True
        if len(meaningful_chars) / len(name_str) < 0.3:
            return True
        return False
    return names.apply(is_meaningless)

def should_delete_poi_by_starting_char_vectorized(names):
    """Vectorized starting character check"""
    def should_delete(name):
        if pd.isna(name):
            return True
        name_str = str(name).strip()
        if not name_str:
            return True
        # Exception: Keep 7-Eleven
        if name_str.lower().startswith("7-eleven") or name_str.startswith("7-11"):
            return False
        first_char = name_str[0]
        return first_char.isdigit() or not first_char.isalpha()
    return names.apply(should_delete)

def has_address_like_name_vectorized(names):
    """Vectorized address-like name detection"""
    pattern = r'Street|Avenue|Road|Boulevard|Drive|Lane|Way|Court|Place'
    return names.str.contains(pattern, case=False, na=False, regex=True)

def has_http_in_address_vectorized(addresses):
    """Vectorized HTTP detection in addresses"""
    return addresses.str.contains('http', case=False, na=False)

def is_ip_address_website_vectorized(websites):
    """Vectorized IP address detection"""
    pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
    return websites.str.match(pattern, na=False)

# ============================================================================
# OPTIMIZED CLEANING FUNCTION
# ============================================================================

def clean_chunk(chunk, enable_ai_validation=False, enable_geocoding=False):
    """
    Optimized cleaning with vectorized operations where possible
    """

    df_clean = chunk.copy()

    # Add status_flag column
    if 'status_flag' not in df_clean.columns:
        df_clean['status_flag'] = ''

    print(f"  Starting chunk with {len(df_clean):,} records")

    # STEP 1: Remove duplicate rows (within chunk)
    before = len(df_clean)
    df_clean = df_clean.drop_duplicates(keep='first')
    removed_duplicates = before - len(df_clean)

    # STEP 2: Remove meaningless POI names (VECTORIZED)
    before = len(df_clean)
    mask_meaningless = is_meaningless_name_vectorized(df_clean['name'])
    problematic_names = ['-', '.', '@@@']
    mask_specific = df_clean['name'].isin(problematic_names)
    df_clean = df_clean[~(mask_meaningless | mask_specific)]
    removed_meaningless = before - len(df_clean)

    # STEP 3: Remove POIs with invalid starting characters (VECTORIZED)
    before = len(df_clean)
    mask_invalid_start = should_delete_poi_by_starting_char_vectorized(df_clean['name'])
    df_clean = df_clean[~mask_invalid_start]
    removed_invalid_start = before - len(df_clean)

    # STEP 4: Flag address-like names (VECTORIZED)
    mask = has_address_like_name_vectorized(df_clean['name'])
    df_clean.loc[mask, 'status_flag'] += 'address-like name; '

    # STEP 5: Remove POIs with HTTP in address (VECTORIZED)
    before = len(df_clean)
    mask_http = has_http_in_address_vectorized(df_clean['address'])
    df_clean = df_clean[~mask_http]
    removed_http = before - len(df_clean)

    # STEP 6: Flag missing addresses
    mask = df_clean['address'].isna()
    df_clean.loc[mask, 'status_flag'] += 'missing address; '

    # STEP 7: Enhanced postcode handling (FIXED)
    df_clean['postcode'] = df_clean['postcode'].astype(str).replace('nan', '')
    df_clean['postcode'] = df_clean['postcode'].replace('', None)

    # Vectorized postcode validation - fixed indexing
    invalid_mask = ~is_valid_us_postcode_vectorized(df_clean['postcode'])

    if invalid_mask.any():
        # Extract postcodes only from invalid rows
        invalid_indices = df_clean[invalid_mask].index
        extracted_postcodes = extract_postcode_vectorized(df_clean.loc[invalid_indices, 'address'])
        valid_extracted = is_valid_us_postcode_vectorized(extracted_postcodes)

        # Update only the valid extracted postcodes
        valid_extracted_indices = invalid_indices[valid_extracted]
        df_clean.loc[valid_extracted_indices, 'postcode'] = extracted_postcodes[valid_extracted].values

        # Set remaining invalid postcodes to None
        invalid_extracted_indices = invalid_indices[~valid_extracted]
        df_clean.loc[invalid_extracted_indices, 'postcode'] = None

    # STEP 8: Clean website_domain (VECTORIZED)
    mask_ip = is_ip_address_website_vectorized(df_clean['website_domain'])
    df_clean.loc[mask_ip, 'website_domain'] = None

    # STEP 9: Flag missing phone and website
    mask_phone = df_clean['phone'].isna()
    df_clean.loc[mask_phone, 'status_flag'] += 'missing phone; '

    mask_website = df_clean['website_domain'].isna()
    df_clean.loc[mask_website, 'status_flag'] += 'missing website; '

    # STEP 10: AI validation (optional - can be slow)
    if enable_ai_validation:
        mask = df_clean['name'].apply(lambda x: not bool(re.search(r'[a-zA-Z]', str(x))))
        indices_to_delete = []
        print(f"  🤖 AI validating {mask.sum()} names...")
        for idx in tqdm(df_clean[mask].index, desc="  AI Validation", leave=False):
            original_name = df_clean.at[idx, 'name']
            category_main = df_clean.at[idx, 'category_main'] if 'category_main' in df_clean.columns else None
            translated_name = translate_and_validate_poi_name(original_name, category_main)
            if translated_name is None:
                indices_to_delete.append(idx)
            elif translated_name != original_name:
                df_clean.at[idx, 'name'] = f"{translated_name} ({original_name})"
                df_clean.at[idx, 'status_flag'] += 'translated; '
        if indices_to_delete:
            df_clean = df_clean.drop(indices_to_delete)

    # STEP 11: Remove records outside USA (VECTORIZED)
    before = len(df_clean)
    outside_mask = is_outside_usa_vectorized(df_clean['latitude'], df_clean['longitude'])
    df_clean = df_clean[~outside_mask]
    removed_outside = before - len(df_clean)

    # STEP 12: Geocode missing addresses (optional - requires API calls)
    if enable_geocoding and GOOGLE_API_KEY != "YOUR_GOOGLE_API_KEY":
        mask_missing_address = df_clean['address'].isna()
        mask_valid_coords = df_clean['latitude'].notna() & df_clean['longitude'].notna()
        mask_to_geocode = mask_missing_address & mask_valid_coords

        geocode_count = mask_to_geocode.sum()
        if geocode_count > 0:
            print(f"  🌍 Geocoding {geocode_count} addresses...")
            for idx in tqdm(df_clean[mask_to_geocode].index, desc="  Geocoding", leave=False):
                lat = df_clean.at[idx, 'latitude']
                lon = df_clean.at[idx, 'longitude']
                address = reverse_geocode(lat, lon, GOOGLE_API_KEY)
                if address:
                    df_clean.at[idx, 'address'] = address
                    status_flag = str(df_clean.at[idx, 'status_flag'])
                    status_flag = status_flag.replace('missing address; ', '')
                    df_clean.at[idx, 'status_flag'] = status_flag.strip()
                time.sleep(GEOCODE_DELAY)

    # Clean up status_flag
    df_clean['status_flag'] = df_clean['status_flag'].str.rstrip('; ')

    # Log stats
    stats = {
        'removed_duplicates': removed_duplicates,
        'removed_meaningless': removed_meaningless,
        'removed_invalid_start': removed_invalid_start,
        'removed_http': removed_http,
        'removed_outside': removed_outside
    }

    return df_clean, stats

def translate_and_validate_poi_name(name, category_main, max_retries=3):
    """Validate if name is proper POI and translate using Azure OpenAI"""
    for attempt in range(max_retries):
        try:
            context = f"Category: {category_main}" if pd.notna(category_main) else "No category info"

            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a POI (Point of Interest) name validator and translator.

Your task:
1. Determine if the given text is a PROPER POI name (business name, landmark, building, etc.)
2. If it's NOT a proper POI name (just numbers, coordinates, dates, generic words, etc.), respond with exactly: DELETE
3. If it IS a proper POI name and in a foreign language, translate it to English

Examples of names to DELETE:
- Pure numbers: "79", "333"
- Coordinates: "18.7690320, 98.9903402"
- Dates: "April 11"
- Generic words: "Good morning", "Extraordinary"

Examples of names to TRANSLATE:
- "中国银行" → "Bank of China"
- "Tienda Mexicana" → "Mexican Store"

Only return the English translation or the word DELETE. Nothing else."""
                    },
                    {
                        "role": "user",
                        "content": f"POI Info: {context}\nName to validate and translate: {name}"
                    }
                ],
                temperature=0.3,
                max_tokens=100
            )

            content = response.choices[0].message.content
            if content is None:
                if attempt < max_retries - 1:
                    continue
                else:
                    return None

            result = content.strip()
            if result.upper() == "DELETE":
                return None
            if not result:
                if attempt < max_retries - 1:
                    continue
                else:
                    return None
            return result

        except Exception as e:
            if attempt < max_retries - 1:
                continue
            else:
                return None
    return None

def reverse_geocode(lat, lon, api_key):
    """Use Google Geocoding API to get address from coordinates"""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lon}", "key": api_key, "language": "en"}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "OK" and len(data["results"]) > 0:
                return data["results"][0]["formatted_address"]
        return None
    except Exception:
        return None

# ============================================================================
# OPTIMIZED MAIN PROCESSING FUNCTION
# ============================================================================

def process_matching_s3_zips(s3_client, s3_bucket_name, local_download_path,
                            local_save_path, cat_df, gadm_boundaries, batch_size=100000,
                            enable_ai_validation=False, enable_geocoding=False):
    """
    Optimized processing with better progress tracking and speed improvements
    """

    os.makedirs(local_download_path, exist_ok=True)
    os.makedirs(local_save_path, exist_ok=True)

    final_cols = ['poi_id','name','website_domain','phone','category_level1','category_level2','category_level3',
                  'category_level4','status','latitude','longitude','address','street','country','locality',
                  'region','postcode','floor_no','open_hours','business_type_detail','price_level','time_spent',
                  'traffic_score','rating','rating_count','data_version_month','hotel_stars']

    source_cols = ['google_id','name','website_domain','category_main','business_status',
                   'latitude','longitude','address','street','postcode','price_level',
                   'country','locality','region','open_hours','rating','rating_count','phone',
                   'time_spent','floor_no','popular_times_data','popular_times_data_kg','hotel_stars','describe_data','categories_list']

    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=s3_bucket_name)

    processed_files_count = 0
    skipped_files_count = 0
    total_stats = {
        'removed_duplicates': 0,
        'removed_meaningless': 0,
        'removed_invalid_start': 0,
        'removed_http': 0,
        'removed_outside': 0
    }

    overall_start_time = time.time()

    for page in pages:
        if 'Contents' in page:
            for obj in page['Contents']:
                object_key = obj['Key']

                if 'United States/2' in object_key and 'big_categories_data' not in object_key:

                    current_date = extract_month_from_filename(object_key)

                    path_parts = object_key.split('/')
                    date_str = path_parts[-2]

                    # Generate output filename as usa_YYYYMMDD.csv
                    if date_str:
                        output_filename = f"LA_{date_str}.csv"
                    else:
                        # Fallback if date not found
                        zip_filename = os.path.basename(object_key)
                        output_filename = zip_filename.replace('.zip', '.csv')

                    local_save_csv_path = os.path.join(local_save_path, output_filename)
                    zip_filename = os.path.basename(object_key)


                    # CHECK IF FILE ALREADY EXISTS - SKIP IF IT DOES
                    if os.path.exists(local_save_csv_path):
                        print(f"\n{'='*80}")
                        print(f"⏭️  SKIPPING: {zip_filename}")
                        print(f"   File already processed: {output_filename}")
                        print(f"{'='*80}")
                        skipped_files_count += 1
                        continue

                    file_start_time = time.time()

                    print(f"\n{'='*80}")
                    print(f"📁 Processing file: {object_key}")
                    print(f"   Output filename: {output_filename}")
                    print(f"{'='*80}")

                    local_zip_path = os.path.join(local_download_path, zip_filename)

                    print(f"⬇️  Downloading to {local_zip_path}...")
                    download_start = time.time()

                    try:
                        s3_client.download_file(s3_bucket_name, object_key, local_zip_path)
                        download_time = time.time() - download_start
                        file_size_mb = os.path.getsize(local_zip_path) / (1024 * 1024)
                        print(f"✅ Download complete in {download_time:.2f}s ({file_size_mb:.2f} MB)")

                        compression_type = 'zip' if object_key.lower().endswith('.zip') else 'infer'

                        # Read CSV in chunks
                        csv_chunker = pd.read_csv(
                            local_zip_path,
                            compression=compression_type,
                            chunksize=batch_size,
                            usecols=lambda x: x in source_cols,
                            low_memory=False,
                            dtype={'postcode': str},
                            encoding='utf-8',
                            encoding_errors='ignore',  # Skip problematic rows
                            on_bad_lines='skip'  # Skip bad lines
                        )

                        chunk_number = 0
                        all_chunks_for_file = []
                        total_input_rows = 0

                        print(f"\n🔄 Processing chunks (batch size: {batch_size:,})...")

                        try:
                            for chunk in csv_chunker:
                                chunk_number += 1
                                chunk_start = time.time()
                                total_input_rows += len(chunk)

                                print(f"\n📦 Chunk {chunk_number}: {len(chunk):,} rows")

                                # ADD THIS: Clean coordinates immediately after loading chunk
                                print("  🔍 Cleaning coordinate data...")
                                initial_rows = len(chunk)

                                # Convert coordinates to numeric, coercing errors to NaN
                                chunk['latitude'] = pd.to_numeric(chunk['latitude'], errors='coerce')
                                chunk['longitude'] = pd.to_numeric(chunk['longitude'], errors='coerce')

                                # Remove rows with invalid coordinates
                                valid_coords = chunk['latitude'].notna() & chunk['longitude'].notna()
                                chunk = chunk[valid_coords].copy()

                                # Additional bounds check (lat: -90 to 90, lon: -180 to 180)
                                valid_lat = (chunk['latitude'] >= -90) & (chunk['latitude'] <= 90)
                                valid_lon = (chunk['longitude'] >= -180) & (chunk['longitude'] <= 180)
                                chunk = chunk[valid_lat & valid_lon].copy()

                                removed_coords = initial_rows - len(chunk)
                                if removed_coords > 0:
                                    print(f"  ⚠️  Removed {removed_coords:,} rows with invalid coordinates")

                                if chunk.empty:
                                    print(f"  ⏭️  No valid data remaining after coordinate cleaning, skipping...")
                                    continue

                                # NOW proceed with GADM spatial join
                                if 'latitude' in chunk.columns and 'longitude' in chunk.columns:
                                    print("  🗺️  Applying GADM spatial join...")
                                    gadm_start = time.time()
                                    chunk = clean_region_with_gadm(chunk, gadm_boundaries)
                                    print(f"  ✅ GADM join completed in {time.time()-gadm_start:.2f}s")

                                missing_cols = [col for col in source_cols if col not in chunk.columns]
                                if missing_cols:
                                    print(f"  ⚠️  Missing columns: {missing_cols}. Filling with NaN.")
                                    for col in missing_cols:
                                        chunk[col] = np.nan

                                # Filter for region == 'Los Angeles'
                                chunk_filtered = chunk[chunk['locality'] == 'Los Angeles'].copy()

                                if chunk_filtered.empty:
                                    print(f"  ⏭️  No data in this chunk, skipping...")
                                    continue

                                print(f"  📍 Found {len(chunk_filtered):,} Los Angeles records")

                                # Apply cleaning
                                print("  🧹 Applying cleaning rules...")
                                clean_start = time.time()
                                chunk_filtered, stats = clean_chunk(
                                    chunk_filtered,
                                    enable_ai_validation=enable_ai_validation,
                                    enable_geocoding=enable_geocoding
                                )
                                clean_time = time.time() - clean_start

                                # Update total stats
                                for key in total_stats:
                                    total_stats[key] += stats[key]

                                print(f"  ✅ Cleaning completed in {clean_time:.2f}s")
                                print(f"  📊 After cleaning: {len(chunk_filtered):,} records remaining")
                                print(f"     - Duplicates removed: {stats['removed_duplicates']:,}")
                                print(f"     - Meaningless names removed: {stats['removed_meaningless']:,}")
                                print(f"     - Invalid start chars removed: {stats['removed_invalid_start']:,}")
                                print(f"     - HTTP in address removed: {stats['removed_http']:,}")
                                print(f"     - Outside USA removed: {stats['removed_outside']:,}")

                                # Category mapping
                                print("  🏷️  Mapping categories...")
                                chunk_filtered = chunk_filtered.merge(
                                    cat_df,
                                    left_on='category_main',
                                    right_on='original_category',
                                    how='left'
                                )

                                chunk_filtered.drop(columns=['original_category'], inplace=True)
                                chunk_filtered.rename(columns={
                                    'target_category': 'category_level3',
                                    'meta_category': 'category_level1',
                                    'middle_category': 'category_level2',
                                    'category_main': 'category_level4'
                                }, inplace=True)

                                # Apply transformations
                                print("  🔧 Applying transformations...")
                                transform_start = time.time()

                                chunk_filtered.rename(columns={
                                    'google_id': 'poi_id',
                                    'business_status': 'status'
                                }, inplace=True)

                                # Vectorized operations where possible
                                chunk_filtered['poi_id'] = chunk_filtered['poi_id'].apply(hash_poi_id)
                                if 'popular_times_data' in chunk_filtered.columns:
                                    chunk_filtered['traffic_score'] = chunk_filtered['popular_times_data'].apply(get_traffic)
                                elif 'popular_times_data_kg' in chunk_filtered.columns:
                                    chunk_filtered['traffic_score'] = chunk_filtered['popular_times_data_kg'].apply(get_traffic)
                                chunk_filtered['data_version_month'] = current_date
                                chunk_filtered['last_verified_date'] = datetime.today().strftime('%d-%m-%Y')
                                chunk_filtered['address'] = chunk_filtered['address'].apply(clean_address)
                                chunk_filtered['latitude'] = chunk_filtered['latitude'].apply(add_random_digits)
                                chunk_filtered['longitude'] = chunk_filtered['longitude'].apply(add_random_digits)
                                chunk_filtered['phone'] = chunk_filtered['phone'].apply(validate_single_phone)
                                chunk_filtered['business_type_detail'] = chunk_filtered.apply(get_dining_category, axis=1)
                                chunk_filtered['price_level'] = chunk_filtered['price_level'].apply(classify_price_level)

                                transform_time = time.time() - transform_start
                                print(f"  ✅ Transformations completed in {transform_time:.2f}s")

                                # Select final columns
                                final_chunk = chunk_filtered[final_cols]
                                all_chunks_for_file.append(final_chunk)

                                chunk_time = time.time() - chunk_start
                                rows_per_sec = len(chunk) / chunk_time if chunk_time > 0 else 0
                                print(f"  ⏱️  Chunk {chunk_number} completed in {chunk_time:.2f}s ({rows_per_sec:.0f} rows/sec)")

                        except StopIteration:
                            print("\n✅ Finished reading all chunks")

                        if all_chunks_for_file:
                            print(f"\n🔗 Concatenating {len(all_chunks_for_file)} chunks...")
                            concat_start = time.time()
                            final_df = pd.concat(all_chunks_for_file, ignore_index=True)
                            print(f"✅ Concatenation completed in {time.time()-concat_start:.2f}s")

                            # Remove duplicates across all chunks
                            print("🧹 Removing cross-chunk duplicates...")
                            before = len(final_df)
                            final_df = final_df.drop_duplicates(keep='first')
                            cross_chunk_dupes = before - len(final_df)
                            if cross_chunk_dupes > 0:
                                print(f"   Removed {cross_chunk_dupes:,} cross-chunk duplicates")

                            # Save file with exact zip name (but .csv extension)
                            print(f"💾 Saving to {local_save_csv_path}...")
                            save_start = time.time()
                            final_df.to_csv(local_save_csv_path, index=False)
                            save_time = time.time() - save_start

                            # Calculate statistics
                            file_time = time.time() - file_start_time

                            print(f"\n{'─'*80}")
                            print(f"✅ File processing complete!")
                            print(f"{'─'*80}")
                            print(f"📄 Saved to: {local_save_csv_path}")
                            print(f"📊 Statistics:")
                            print(f"   - Input rows: {total_input_rows:,}")
                            print(f"   - Output rows: {len(final_df):,}")
                            print(f"   - Reduction: {(1 - len(final_df)/total_input_rows)*100:.1f}%")
                            print(f"⏱️  Total time: {file_time:.2f}s")
                            print(f"   - Download: {download_time:.2f}s")
                            print(f"   - Processing: {file_time-download_time-save_time:.2f}s")
                            print(f"   - Saving: {save_time:.2f}s")
                            print(f"📈 Processing speed: {total_input_rows/file_time:.0f} rows/sec")
                            print(f"{'─'*80}")

                            processed_files_count += 1
                        else:
                            print(f"❌ No data found in {object_key}. File not saved.")

                    except Exception as e:
                        print(f"❌ Fatal Error processing {object_key}: {e}")
                        import traceback
                        traceback.print_exc()

                    finally:
                        if os.path.exists(local_zip_path):
                            os.remove(local_zip_path)
                            print(f"🗑️  Cleaned up temporary file: {local_zip_path}")

    # Print overall summary
    total_time = time.time() - overall_start_time
    print(f"\n{'='*80}")
    print(f"🎉 PROCESSING COMPLETE")
    print(f"{'='*80}")
    print(f"📁 Files processed: {processed_files_count}")
    print(f"⏭️  Files skipped (already processed): {skipped_files_count}")
    print(f"📊 Total files encountered: {processed_files_count + skipped_files_count}")
    print(f"⏱️  Total runtime: {total_time/60:.2f} minutes ({total_time:.2f} seconds)")
    print(f"\n📊 Total records removed across all files:")
    total_removed = sum(total_stats.values())
    for category, count in total_stats.items():
        percentage = (count/total_removed*100) if total_removed > 0 else 0
        print(f"   - {category}: {count:,} ({percentage:.1f}%)")
    print(f"   - TOTAL REMOVED: {total_removed:,}")
    print(f"{'='*80}\n")

    return processed_files_count, s

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':

    print("=" * 80)
    print("🚀 DATA CLEANING - OPTIMIZED VERSION")
    print("=" * 80)
    print(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Load data
    print("\n📂 Loading reference data...")
    load_start = time.time()

    try:
        import geopandas as gpd
        gadm_boundaries = gpd.read_file('/content/drive/MyDrive/pipeline_sample/usa_admin.geojson')
        print(f"   ✅ GADM boundaries loaded: {len(gadm_boundaries):,} features")
    except Exception as e:
        print(f"   ❌ Error loading GADM boundaries: {e}")
        gadm_boundaries = None

    try:
        cat_df = pd.read_csv('/content/drive/MyDrive/pipeline_sample/xmap_poi_categorization.csv')[
            ['original_category','target_category','middle_category','meta_category']
        ]
        print(f"   ✅ Category mapping loaded: {len(cat_df):,} categories")
    except Exception as e:
        print(f"   ❌ Error loading category mapping: {e}")
        cat_df = None

    load_time = time.time() - load_start
    print(f"   ⏱️  Loading completed in {load_time:.2f}s")

    # Configuration
    LOCAL_DOWNLOAD_PATH = '/tmp/s3_data_download'
    LOCAL_SAVE_PATH = '/content/drive/MyDrive/pipeline_sample'
    BATCH_ROWS = 200000

    # Feature flags
    ENABLE_AI_VALIDATION = False
    ENABLE_GEOCODING = False

    print(f"\n⚙️  Configuration:")
    print(f"   - Batch size: {BATCH_ROWS:,} rows")
    print(f"   - AI Validation: {'✅ ENABLED' if ENABLE_AI_VALIDATION else '❌ DISABLED'}")
    print(f"   - Geocoding: {'✅ ENABLED' if ENABLE_GEOCODING else '❌ DISABLED'}")
    print(f"   - Download path: {LOCAL_DOWNLOAD_PATH}")
    print(f"   - Save path: {LOCAL_SAVE_PATH}")
    print("=" * 80)

    # Initialize S3 client (uncomment and configure)
    # import boto3
    # s3_client = boto3.client('s3',
    #     aws_access_key_id='YOUR_ACCESS_KEY',
    #     aws_secret_access_key='YOUR_SECRET_KEY',
    #     region_name='YOUR_REGION'
    # )
    # s3_bucket_name = 'YOUR_BUCKET_NAME'

    # Process files
    try:
        total_processed_files, s = process_matching_s3_zips(
            s3_client,
            s3_bucket_name,
            LOCAL_DOWNLOAD_PATH,
            LOCAL_SAVE_PATH,
            cat_df,
            gadm_boundaries,
            BATCH_ROWS,
            enable_ai_validation=ENABLE_AI_VALIDATION,
            enable_geocoding=ENABLE_GEOCODING
        )

        print(f"\n✨ Complete! Total files processed: {total_processed_files}")
        print(f"🏁 End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except KeyboardInterrupt:
        print("\n\n⚠️  Processing interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

"""# Adding Open/Close Dates"""

import os
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import re
from collections import defaultdict
import shutil

# ============================================================================
# POI STATUS ANALYZER - POST-PROCESSING (ENHANCED WITH EDGE CASES)
# ============================================================================

class POIStatusAnalyzer:
    """
    Analyzes POI status changes across all processed files
    and updates ORIGINAL files with open_date, close_date, and status_changed columns

    Enhanced with edge case handling:
    - Window-boundary guard: No close_date if never seen open and first record is closed
    - Reopening detection: No close_date if POI reopened after closure
    """

    def __init__(self, input_folder, backup_folder=None):
        """
        Initialize analyzer

        Args:
            input_folder: Folder containing LA_YYYYMMDD.csv files (will be updated in-place)
            backup_folder: Optional folder to backup original files before modification
        """
        self.input_folder = input_folder
        self.backup_folder = backup_folder
        self.first_dataset_month = None

        # Define status categories for consistent handling
        self.open_statuses = {'open', 'open 24 hours', 'operational'}
        self.closed_statuses = {
            'closed', 'closed_temporarily', 'temporarily closed',
            'permanently closed', 'closed permanently'
        }

        if backup_folder:
            os.makedirs(backup_folder, exist_ok=True)

        self.all_files = []
        self.poi_history = {}
        self.poi_dates = {}

        # Edge case tracking
        self.edge_case_stats = {
            'boundary_guard': 0,
            'reopened': 0,
            'closed_first_month': 0
        }

    def normalize_status(self, status):
        """Normalize status string for consistent comparison"""
        if pd.isna(status):
            return 'unknown'
        return str(status).strip().lower()

    def extract_month_from_filename(self, filename):
        """Extract YYYY-MM from LA_YYYYMMDD.csv"""
        match = re.search(r'LA_(\d{8})\.csv', filename)
        if match:
            date_str = match.group(1)
            year = date_str[:4]
            month = date_str[4:6]
            return f"{year}-{month}"
        return None

    def load_all_files(self):
        """Load all LA_*.csv files from input folder and sort by date"""
        print("=" * 80)
        print("📂 Scanning for processed files...")
        print("=" * 80)

        files = [f for f in os.listdir(self.input_folder) if f.startswith('LA_') and f.endswith('.csv')]

        if not files:
            print("❌ No LA_*.csv files found in the input folder!")
            return False

        # Sort files by date
        file_dates = []
        for f in files:
            month = self.extract_month_from_filename(f)
            if month:
                file_dates.append((f, month))

        file_dates.sort(key=lambda x: x[1])
        self.all_files = file_dates

        # Store first dataset month for later use
        self.first_dataset_month = self.all_files[0][1]

        print(f"✅ Found {len(self.all_files)} files")
        print(f"📅 Date range: {self.all_files[0][1]} to {self.all_files[-1][1]}")
        print("\n📋 Files to process:")
        for filename, month in self.all_files:
            print(f"   - {filename} ({month})")
        print()

        return True

    def backup_files(self):
        """Create backup of original files before modification"""
        if not self.backup_folder:
            return

        print("=" * 80)
        print("💾 Creating backup of original files...")
        print("=" * 80)

        for filename, month in self.all_files:
            src = os.path.join(self.input_folder, filename)
            dst = os.path.join(self.backup_folder, filename)
            shutil.copy2(src, dst)
            print(f"   ✅ Backed up: {filename}")

        print(f"\n✅ All files backed up to: {self.backup_folder}")
        print()

    def build_poi_history(self):
        """Build complete history of all POIs across all months"""
        print("=" * 80)
        print("🔍 Building POI history across all files...")
        print("=" * 80)

        for filename, month in self.all_files:
            print(f"📖 Reading {filename} ({month})...")

            file_path = os.path.join(self.input_folder, filename)

            try:
                df = pd.read_csv(file_path, dtype={'poi_id': str})

                for _, row in df.iterrows():
                    poi_id = str(row['poi_id'])
                    status = self.normalize_status(row.get('status', 'UNKNOWN'))

                    if poi_id not in self.poi_history:
                        self.poi_history[poi_id] = []

                    # Store month and normalized status
                    self.poi_history[poi_id].append({
                        'month': month,
                        'status': status
                    })

                print(f"   ✅ Processed {len(df):,} records")

            except Exception as e:
                print(f"   ❌ Error reading {filename}: {e}")

        print(f"\n✅ Total unique POIs tracked: {len(self.poi_history):,}")
        print()

    def determine_open_close_dates(self):
        """
        Determine open_date and close_dates for each POI with edge case handling

        Edge cases:
        1. Window-boundary guard: If never seen open AND first record is closed,
           likely closed before observation window → close_date = None
        2. Reopening detection: If POI reopened after closure → close_date = None
        """
        print("=" * 80)
        print("📊 Determining open and close dates with edge case handling...")
        print("=" * 80)

        stats = {
            'total_pois': 0,
            'with_open_date': 0,
            'with_close_dates': 0,
            'ongoing': 0,
            'existing_in_first_month': 0
        }

        for poi_id, history in self.poi_history.items():
            # Sort history by month
            history.sort(key=lambda x: x['month'])

            first_appearance = history[0]

            # Determine open_date (None if in first month)
            if first_appearance['month'] == self.first_dataset_month:
                open_date = None
                stats['existing_in_first_month'] += 1
            else:
                open_date = first_appearance['month']

            # Find LAST time POI was open
            last_open_idx = None
            for i, record in enumerate(history):
                if record['status'] in self.open_statuses:
                    last_open_idx = i

            # Start looking for closures AFTER last open
            start_idx = (last_open_idx + 1) if last_open_idx is not None else 0

            # Find FIRST permanent closure after last open
            first_perm_close_idx = None
            for i in range(start_idx, len(history)):
                if history[i]['status'] in self.closed_statuses:
                    first_perm_close_idx = i
                    break

            close_date = None

            if first_perm_close_idx is not None:
                # EDGE CASE 1: Window-boundary guard
                # If never seen open AND first record is closed, likely closed before window
                if last_open_idx is None and first_perm_close_idx == 0:
                    self.edge_case_stats['boundary_guard'] += 1
                    close_date = None
                else:
                    # EDGE CASE 2: Check for reopening after closure
                    reopened = False
                    for i in range(first_perm_close_idx + 1, len(history)):
                        if history[i]['status'] in self.open_statuses:
                            reopened = True
                            self.edge_case_stats['reopened'] += 1
                            break

                    if not reopened:
                        # Valid closure
                        close_month = history[first_perm_close_idx]['month']
                        # Don't record if closure is in first month
                        if close_month != self.first_dataset_month:
                            close_date = close_month
                        else:
                            self.edge_case_stats['closed_first_month'] += 1

            self.poi_dates[poi_id] = {
                'open_date': open_date,
                'close_date': close_date,
                'history': history
            }

            # Update statistics
            stats['total_pois'] += 1
            if open_date:
                stats['with_open_date'] += 1
            if close_date:
                stats['with_close_dates'] += 1

            # Check if currently ongoing
            last_status = history[-1]['status']
            if last_status not in self.closed_statuses:
                stats['ongoing'] += 1

        print(f"📈 Overall Statistics:")
        print(f"   - Total POIs: {stats['total_pois']:,}")
        print(f"   - POIs already existing in first month (open_date=None): {stats['existing_in_first_month']:,}")
        print(f"   - POIs with open_date: {stats['with_open_date']:,}")
        print(f"   - POIs with close_date: {stats['with_close_dates']:,}")
        print(f"   - Currently ongoing POIs: {stats['ongoing']:,}")
        print(f"\n🛡️  Edge Cases Handled:")
        print(f"   - Boundary guard applied: {self.edge_case_stats['boundary_guard']:,} POIs")
        print(f"   - Reopened (closure cancelled): {self.edge_case_stats['reopened']:,} POIs")
        print(f"   - Closed in first month: {self.edge_case_stats['closed_first_month']:,} POIs")
        print()

        return stats

    def get_close_date_for_month(self, poi_id, current_month):
        """
        Get the applicable close_date for a POI in a specific month.
        Returns close_date if POI is currently closed, None if currently open.
        """
        if poi_id not in self.poi_dates:
            return None

        poi_data = self.poi_dates[poi_id]
        history = poi_data['history']
        close_date = poi_data['close_date']

        if not close_date:
            return None

        # Find the status in the current month
        current_status = None
        for record in history:
            if record['month'] == current_month:
                current_status = record['status']
                break

        # If currently open in this month, return None
        if current_status and current_status in self.open_statuses:
            return None

        # Return close_date if it's on or before current month
        if close_date <= current_month:
            return close_date

        return None

    def update_csv_files(self):
        """Update original CSV files with open_date, close_date, and status_changed columns"""
        print("=" * 80)
        print("✏️  Updating original CSV files...")
        print("=" * 80)

        monthly_stats = []

        for filename, month in self.all_files:
            print(f"\n📝 Updating {filename} ({month})...")

            file_path = os.path.join(self.input_folder, filename)

            try:
                # Read file
                df = pd.read_csv(file_path, dtype={'poi_id': str})

                # Initialize new columns
                df['open_date'] = None
                df['close_date'] = None
                df['status_changed'] = None

                # Track status changes
                opened_count = 0
                closed_count = 0

                # Update each row
                for idx, row in df.iterrows():
                    poi_id = str(row['poi_id'])

                    if poi_id in self.poi_dates:
                        dates = self.poi_dates[poi_id]

                        # Set open_date
                        df.at[idx, 'open_date'] = dates['open_date']

                        # Set close_date based on current status
                        close_date = self.get_close_date_for_month(poi_id, month)
                        df.at[idx, 'close_date'] = close_date

                        # Determine status_changed
                        current_status = self.normalize_status(row.get('status', 'UNKNOWN'))

                        # Check if opened this month
                        if dates['open_date'] == month:
                            df.at[idx, 'status_changed'] = 'opened this month'
                            opened_count += 1
                        # Check if closed this month
                        elif current_status in self.closed_statuses and close_date == month:
                            # Verify this is a NEW closure (not already closed in previous month)
                            history = dates['history']
                            is_new_closure = True
                            for i, record in enumerate(history):
                                if record['month'] == month:
                                    if i > 0:
                                        prev_status = history[i-1]['status']
                                        if prev_status in self.closed_statuses:
                                            is_new_closure = False
                                    break

                            if is_new_closure:
                                df.at[idx, 'status_changed'] = 'closed this month'
                                closed_count += 1

                # Calculate active count
                active_count = (df['close_date'].isna() | (df['close_date'] > month)).sum()

                # Save updated file
                df.to_csv(file_path, index=False)

                print(f"   ✅ Updated successfully!")
                print(f"   📊 Statistics:")
                print(f"      - Total records: {len(df):,}")
                print(f"      - 🆕 Opened this month: {opened_count:,}")
                print(f"      - 🚫 Closed this month: {closed_count:,}")
                print(f"      - ✅ Active this month: {active_count:,}")

                monthly_stats.append({
                    'month': month,
                    'filename': filename,
                    'total_records': len(df),
                    'opened': opened_count,
                    'closed': closed_count,
                    'active': active_count
                })

            except Exception as e:
                print(f"   ❌ Error updating {filename}: {e}")
                import traceback
                traceback.print_exc()

        return monthly_stats

    def generate_summary_report(self, overall_stats, monthly_stats):
        """Generate summary report"""
        print("\n" + "=" * 80)
        print("📊 Generating summary report...")
        print("=" * 80)

        summary_file = os.path.join(self.input_folder, 'poi_analysis_summary.txt')

        with open(summary_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("POI STATUS ANALYSIS - SUMMARY REPORT (ENHANCED)\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Date Range: {self.all_files[0][1]} to {self.all_files[-1][1]}\n")
            f.write(f"Total Files Analyzed: {len(self.all_files)}\n\n")

            f.write("-" * 80 + "\n")
            f.write("OVERALL STATISTICS\n")
            f.write("-" * 80 + "\n")
            f.write(f"Total Unique POIs: {overall_stats['total_pois']:,}\n")
            f.write(f"POIs Existing in First Month (open_date=None): {overall_stats['existing_in_first_month']:,}\n")
            f.write(f"POIs with Open Date: {overall_stats['with_open_date']:,}\n")
            f.write(f"POIs with Close Date: {overall_stats['with_close_dates']:,}\n")
            f.write(f"Currently Active POIs: {overall_stats['ongoing']:,}\n\n")

            f.write("-" * 80 + "\n")
            f.write("EDGE CASES HANDLED\n")
            f.write("-" * 80 + "\n")
            f.write(f"Boundary Guard Applied: {self.edge_case_stats['boundary_guard']:,} POIs\n")
            f.write(f"  (Never seen open AND first record is closed)\n")
            f.write(f"Reopening Detected: {self.edge_case_stats['reopened']:,} POIs\n")
            f.write(f"  (POI reopened after closure - close_date cancelled)\n")
            f.write(f"Closed in First Month: {self.edge_case_stats['closed_first_month']:,} POIs\n\n")

            f.write("-" * 80 + "\n")
            f.write("MONTHLY BREAKDOWN\n")
            f.write("-" * 80 + "\n")

            for stat in monthly_stats:
                f.write(f"\n{stat['month']} ({stat['filename']}):\n")
                f.write(f"  - Total Records: {stat['total_records']:,}\n")
                f.write(f"  - Opened: {stat['opened']:,}\n")
                f.write(f"  - Closed: {stat['closed']:,}\n")
                f.write(f"  - Active: {stat['active']:,}\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("\nCOLUMNS ADDED:\n")
            f.write("  - open_date: First month POI appeared (None if existed in first month)\n")
            f.write("  - close_date: Closure date with edge case handling (see below)\n")
            f.write("  - status_changed: 'opened this month', 'closed this month', or null\n")
            f.write("\nCLOSE_DATE LOGIC:\n")
            f.write("  - None if POI is currently open\n")
            f.write("  - None if never seen open AND first record is closed (boundary guard)\n")
            f.write("  - None if POI reopened after closure\n")
            f.write("  - None if closed in first month\n")
            f.write("  - Otherwise: Month when POI permanently closed\n")
            f.write("=" * 80 + "\n")

        print(f"✅ Summary report saved to: {summary_file}")
        print()

    def run_analysis(self):
        """Run complete analysis pipeline"""
        start_time = datetime.now()

        print("\n")
        print("🚀 " + "=" * 76)
        print("🚀 POI STATUS ANALYZER - ENHANCED WITH EDGE CASE HANDLING")
        print("🚀 " + "=" * 76)
        print(f"⏰ Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Step 1: Load all files
        if not self.load_all_files():
            return

        # Step 2: Backup files (optional)
        if self.backup_folder:
            self.backup_files()

        # Step 3: Build POI history
        self.build_poi_history()

        # Step 4: Determine open/close dates with edge case handling
        overall_stats = self.determine_open_close_dates()

        # Step 5: Update CSV files
        monthly_stats = self.update_csv_files()

        # Step 6: Generate summary report
        self.generate_summary_report(overall_stats, monthly_stats)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print("=" * 80)
        print("🎉 ANALYSIS COMPLETE!")
        print("=" * 80)
        print(f"✅ All CSV files have been updated in-place")
        print(f"✅ New columns added: open_date, close_date, status_changed")
        print(f"🛡️  Edge cases handled:")
        print(f"   - Boundary guard: {self.edge_case_stats['boundary_guard']:,} POIs")
        print(f"   - Reopening: {self.edge_case_stats['reopened']:,} POIs")
        print(f"   - Closed in first month: {self.edge_case_stats['closed_first_month']:,} POIs")
        print(f"⏱️  Total runtime: {duration:.2f} seconds ({duration/60:.2f} minutes)")
        print(f"🏁 End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if self.backup_folder:
            print(f"\n💾 Original files backed up to: {self.backup_folder}")

        print("=" * 80)
        print()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':

    # Configuration
    INPUT_FOLDER = '/content/drive/MyDrive/pipeline_sample'
    BACKUP_FOLDER = '/content/drive/MyDrive/pipeline_sample/backup'

    print("\n⚙️  Configuration:")
    print(f"   - Input folder: {INPUT_FOLDER}")
    print(f"   - Backup folder: {BACKUP_FOLDER}")
    print(f"\n⚠️  WARNING: This script will UPDATE files in-place!")
    print(f"   Original files will be modified with new columns.")

    # Uncomment for user confirmation
    # response = input("\n   Continue? (yes/no): ")
    # if response.lower() != 'yes':
    #     print("   ❌ Aborted by user")
    #     exit()

    print()

    # Create analyzer
    analyzer = POIStatusAnalyzer(INPUT_FOLDER, BACKUP_FOLDER)

    # Run analysis
    try:
        analyzer.run_analysis()

        print("\n✨ Updated files location:")
        print(f"   📁 {INPUT_FOLDER}/LA_*.csv (updated in-place)")
        print(f"   📊 {INPUT_FOLDER}/poi_analysis_summary.txt")
        if BACKUP_FOLDER:
            print(f"   💾 {BACKUP_FOLDER}/ (original backups)")
        print()

    except KeyboardInterrupt:
        print("\n\n⚠️  Analysis interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

"""# Branding"""

import os
import pandas as pd

path = '/content/drive/MyDrive/pipeline_sample'
brand_df = pd.read_csv('/content/drive/MyDrive/pipeline_sample/branding_usa_configs.csv')

final_cols = ['poi_id','name','website_domain','phone','category_level1','category_level2','category_level3',
              'category_level4','status','latitude','longitude','address','street','country','locality',
              'region','postcode','floor_no','open_hours','business_type_detail','price_level','time_spent',
              'traffic_score','rating','rating_count','data_version_month','hotel_stars',
              'status_changed','open_date','close_date','chain_flag','brand_name']

for file in os.listdir(path):
    file_path = os.path.join(path, file)
    if os.path.isfile(file_path) and file.startswith(('LA')) and '_fix' not in file:
        print(f"Processing: {file}")

        df = pd.read_csv(file_path)
        df.drop_duplicates(subset='poi_id',inplace=True)

        if 'brand_name' in df.columns:
            df.drop(columns=['brand_name'], inplace=True)

        # Merge with branding data on name, website_domain, and category_level4
        df = df.merge(
            brand_df[['name', 'website_domain', 'original_category', 'brand_name','user_category']],
            left_on=['name', 'website_domain', 'category_level4'],
            right_on=['name', 'website_domain', 'original_category'],
            how='left'
        )

        # Update category_level3 with user_category where match exists
        df.loc[df['user_category'].notna(), 'category_level3'] = df.loc[df['user_category'].notna(), 'user_category']

        # Drop the user_category column after updating category_level3
        if 'user_category' in df.columns:
            df.drop(columns=['user_category'], inplace=True)

        if 'original_category' in df.columns:
            df.drop(columns=['original_category'], inplace=True)

        # Create chain_flag: True if brand_name exists, False otherwise
        df['chain_flag'] = df['brand_name'].notna()

        # Select final columns
        df = df[final_cols]

        # Save back to file
        df.to_csv(file_path, index=False)
        print(f"  ✅ Saved {len(df):,} rows ({df['chain_flag'].sum():,} chains identified)")

print("✨ All files processed!")

"""# Divide into category files"""

import pandas as pd
import os
from pathlib import Path
import glob

# Configuration
source_folder = '/content/drive/MyDrive/pipeline_sample/'
output_base = '/content/drive/MyDrive/pipeline_sample/usa/'

# Get all LA files
la_files = glob.glob(os.path.join(source_folder, 'LA_????????.csv'))
la_files.sort()

print(f"Found {len(la_files)} LA files")

# Process each file
for file_path in la_files:
    filename = os.path.basename(file_path)
    # Extract date from filename: LA_YYYYMMDD.csv
    date_part = filename.split('_')[1].split('.')[0]
    year = date_part[:4]
    month = date_part[4:6]

    print(f"\nProcessing {filename} ({year}-{month})...")

    # Read the CSV
    try:
        df = pd.read_csv(file_path)
        print(f"  Loaded {len(df)} rows")

        # Group by category_level1 and category_level2
        grouped = df.groupby(['category_level1', 'category_level2'])

        print(f"  Found {len(grouped)} unique category combinations")

        # Process each group
        for (cat1, cat2), group_df in grouped:
            # Skip if categories are null
            if pd.isna(cat1) or pd.isna(cat2):
                continue

            # Create output directory
            output_dir = os.path.join(output_base, year, month, cat1)
            os.makedirs(output_dir, exist_ok=True)

            # Create output filename
            output_file = os.path.join(output_dir, f"LA - {cat2}.csv")

            # Check if file exists - if so, append
            if os.path.exists(output_file):
                # Append without header
                group_df.to_csv(output_file, mode='a', header=False, index=False)
                print(f"    Appended {len(group_df)} rows to {cat1}/{cat2}")
            else:
                # Write new file with header
                group_df.to_csv(output_file, index=False)
                print(f"    Created {cat1}/{cat2} with {len(group_df)} rows")

    except Exception as e:
        print(f"  Error processing {filename}: {str(e)}")
        continue

print("\n✓ Processing complete!")

# Summary of output structure
print("\nOutput structure summary:")
for year_dir in sorted(os.listdir(output_base)):
    year_path = os.path.join(output_base, year_dir)
    if os.path.isdir(year_path):
        for month_dir in sorted(os.listdir(year_path)):
            month_path = os.path.join(year_path, month_dir)
            if os.path.isdir(month_path):
                for cat_dir in sorted(os.listdir(month_path)):
                    cat_path = os.path.join(month_path, cat_dir)
                    if os.path.isdir(cat_path):
                        file_count = len([f for f in os.listdir(cat_path) if f.endswith('.csv')])
                        print(f"  usa/{year_dir}/{month_dir}/{cat_dir}/ - {file_count} files")