# USA POI Data Pipeline

A modular, production-ready pipeline for processing Point of Interest (POI) data from S3, with data cleaning, transformation, and quality scoring.

## Table of Contents

- [Overview](#overview)
- [Feature Origins](#feature-origins)
  - [Functionalities Borrowed from extended_data_pipeline.py](#functionalities-borrowed-from-extended_data_pipelinepy)
  - [Direct Source Columns](#direct-source-columns)
  - [Derived Features](#derived-features)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)

---

## Overview

This pipeline processes raw POI data from an S3 bucket, applies data cleaning rules, transforms fields into a standardized schema, and outputs clean CSV files. The architecture uses a modular transformer pattern, where each transformer handles a specific domain of transformations.

**Key Features:**
- Multi-version processing with status change detection between consecutive versions
- 4-level category hierarchy mapping
- Quality scoring based on verification signals
- Simplified open hours format for better readability

---

## Feature Origins

### Functionalities Borrowed from extended_data_pipeline.py

The following core functionalities were adapted from the original `extended_data_pipeline.py` monolithic script and refactored into the modular transformer architecture:

| Functionality | Original Location | New Location | Description |
|---------------|-------------------|--------------|-------------|
| **POI ID Hashing** | `hash_poi_id()` | `CoreTransformer.hash_poi_id()` | MD5 hash of google_id for unique identifier |
| **Price Level Classification** | `classify_price_level()` | `MetricsTransformer.standardize_price_level()` | Convert price strings to 1-5 scale |
| **Dining Type Classification** | `get_dining_category()` | `CategoryTransformer.classify_dining_type()` | Multi-factor scoring for restaurant classification |
| **Traffic Score Calculation** | `get_traffic()` | `MetricsTransformer.calculate_traffic_score()` | Extract average popularity from popular_times_data |
| **Phone Validation** | `validate_single_phone()` | `QualityTransformer.validate_phone()` | Validate phone numbers using phonenumbers library |
| **Address Cleaning** | `clean_address()` | `LocationTransformer.clean_address()` | Remove plus code prefixes from addresses |
| **Coordinate Noise** | `add_random_digits()` | `LocationTransformer.add_coordinate_noise()` | Add privacy noise to coordinates |
| **Postcode Validation** | `is_valid_us_postcode_vectorized()` | `LocationTransformer.validate_us_postcode()` | Validate US postal code format (5 or 5+4 digits) |
| **Postcode Extraction** | `extract_postcode_vectorized()` | `LocationTransformer.extract_postcode_from_address()` | Extract postal code from address string |
| **USA Boundary Check** | `is_outside_usa_vectorized()` | `LocationTransformer.is_outside_usa_vectorized()` | Filter records outside continental USA |
| **Meaningless Name Detection** | `is_meaningless_name_vectorized()` | `CoreTransformer.is_valid_name()` | Detect invalid POI names |
| **GADM Spatial Join** | `clean_region_with_gadm()` | `LocationTransformer.apply_gadm_boundaries()` | Derive region/locality from GADM boundaries using coordinates |
| **POI Status Analysis** | `POIStatusAnalyzer` class | `StatusTransformer` | Track open/close dates across multiple months |

---

### Direct Source Columns

These fields are taken directly from the source data with minimal or no transformation:

| Output Field | Source Column | Transformation |
|--------------|---------------|----------------|
| `name` | `name` | Whitespace normalization only |
| `latitude` | `latitude` | Privacy noise added (see Derived Features) |
| `longitude` | `longitude` | Privacy noise added (see Derived Features) |
| `street` | `street` | Direct copy |
| `country_code` | `country` | Direct copy |
| `country_isocode` | `country` | Direct copy |
| `rating_count` | `rating_count` | Direct copy |
| `average_rating` | `rating` | Direct copy (validated 0-5 range) |
| `hotel_star_rating` | `hotel_stars` | Direct copy |
| `floor_level` | `floor_no` | Normalized format (see Derived Features) |
| `website_domain` | `website_domain` | Direct copy |
| `phone` | `phone` | Validated format (see Derived Features) |

**Note:** `region` and `locality` are NOT taken directly from source columns. They are derived from GADM administrative boundaries using POI coordinates. See Derived Features section.

---

### Derived Features

These fields are computed or derived from one or more source columns. Each includes the transformation logic:

#### 1. `poi_id`
- **Source**: `google_id`
- **Transformer**: `CoreTransformer.hash_poi_id()`
- **Logic**:
  ```
  MD5 hash of the google_id string
  Result: 32-character hexadecimal string
  Example: "ChIJ..." -> "a1b2c3d4e5f6..."
  ```

#### 2. `chain_flag`
- **Source**: `name`, `website_domain` + brand config file
- **Transformer**: `CoreTransformer.detect_chain()`
- **Logic**:
  ```
  1. Look up (name, website_domain) pair in brand config
  2. If match found -> "yes"
  3. Look up name alone in brand config
  4. If match found -> "yes"
  5. Look up website_domain in brand config
  6. If match found -> "yes"
  7. Otherwise -> "no"
  ```

#### 3. `brand_name`
- **Source**: `name`, `website_domain` + brand config file
- **Transformer**: `CoreTransformer.match_brand()`
- **Logic**:
  ```
  Same lookup as chain_flag, returns the matched brand name or None
  Priority: (name + domain) > name only > domain only
  ```

#### 4. `category_level_1`, `category_level_2`, `category_level_3`, `category_level_4`
- **Source**: `category_main` + category mapping file
- **Transformer**: `CategoryTransformer.transform_categories()`
- **Logic**:
  ```
  Lookup category_main in mapping file:
  - category_level_1 = meta_category (broadest, e.g., "Food & Beverage")
  - category_level_2 = middle_category (e.g., "Restaurants & Eateries")
  - category_level_3 = target_category (most specific, e.g., "Fast Food Restaurant")
  - category_level_4 = original_category (original category_main value)
  ```

#### 5. `dining_type`
- **Source**: `name`, `category_main`, `categories_list`, `price_level`, `describe_data`
- **Transformer**: `CategoryTransformer.classify_dining_type()`
- **Logic**: Multi-factor weighted scoring system
  ```
  Only applies to restaurants (detected via category keywords)

  QSR Score (Quick Service Restaurant):
  +5 points: Name matches QSR brand (McDonald's, Subway, etc.)
  +4 points: Category contains "fast food" or "fast_food_restaurant"
  +2 points: Offerings include "quick bite"
  +2 points: Service includes "drive-through" or "counter service"
  +2 points: Price level = 1
  +1 point:  Planning shows "doesn't accept reservations"

  Fine Dining Score:
  +5 points: Price level = 4 or 5
  +2 points: Price level = 3
  +4 points: Atmosphere includes "upscale"
  +2 points: Offerings include "serves wine" or "serves cocktails"
  +3 points: Planning shows "accepts reservations"

  Family Dining Score:
  +4 points: Crowd includes "family-friendly"
  +2 points: Crowd includes "good for groups"
  +3 points: Price level = 2
  +1 point:  Price level = 3
  +2 points: Crowd includes "good for kids"

  Casual Dining Score:
  +4 points: Atmosphere includes "casual"
  +2 points: Service includes "serves dine-in"
  +2 points: Price level = 2 or 3

  Decision Logic:
  - If QSR score >= 5 -> "QSR"
  - If Fine Dining score >= 7 -> "Fine Dining"
  - If Family Dining score >= 6 -> "Family Dining"
  - Otherwise -> highest scoring category
  - If all scores = 0, fallback based on price_level:
    - Price 1 -> "QSR"
    - Price 4-5 -> "Fine Dining"
    - Price 2 -> "Family Dining"
    - Otherwise -> "Casual Dining"
  ```

#### 6. `status`
- **Source**: `business_status`
- **Transformer**: `StatusTransformer.normalize_status()`
- **Logic**:
  ```
  Normalize to: "Open", "Closed", "Temporarily Closed", or "Unknown"

  Mapping (only values present in source data):
  - "open", "open 24 hours" -> "Open"
  - "permanently closed" -> "Closed"
  - "temporarily closed" -> "Temporarily Closed"
  - Other/null -> "Unknown"
  ```

#### 7. `latitude` (with noise)
- **Source**: `latitude`
- **Transformer**: `LocationTransformer.add_coordinate_noise()`
- **Logic**:
  ```
  For privacy protection, add random digits after 6th decimal place:
  1. Truncate/pad decimal to 6 places
  2. Append 2 random digits (10-99)
  Example: 34.052234 -> 34.05223467
  Precision change: ~1m -> ~0.01m (negligible location change)
  ```

#### 8. `longitude` (with noise)
- **Source**: `longitude`
- **Transformer**: `LocationTransformer.add_coordinate_noise()`
- **Logic**: Same as latitude

#### 9. `address_full`
- **Source**: `address`
- **Transformer**: `LocationTransformer.clean_address()`
- **Logic**:
  ```
  Remove Google Plus Code prefix from address:
  If address starts with plus code (contains '+'):
    Remove first comma-separated component
  Example: "WXYZ+AB, 123 Main St, City" -> "123 Main St, City"
  ```

#### 10. `postal_code`
- **Source**: `postcode`, `address`
- **Transformer**: `LocationTransformer.fix_postcodes()`
- **Logic**:
  ```
  1. Validate existing postcode against US format (5 digits or 5+4)
  2. If invalid or missing:
     - Extract last 5-digit or 5+4 pattern from address
     - Validate extracted postcode
  3. If still invalid -> None

  Regex: \b\d{5}(?:-\d{4})?\b
  ```

#### 11. `region`
- **Source**: `latitude`, `longitude` + GADM boundaries
- **Transformer**: `LocationTransformer.apply_gadm_boundaries()`
- **Logic**:
  ```
  Derive region (state/province) from GADM administrative boundaries:

  1. Create point geometry from POI coordinates
  2. Perform spatial join with GADM boundaries
  3. Extract NAME_1 (first-level admin division) as region
  4. This replaces source region_level_1 for accuracy

  Example: Coordinates (34.052, -118.243) -> "California"

  Note: Requires GADM_PATH environment variable to be set.
  If GADM boundaries not available, region will be None.
  ```

#### 12. `locality`
- **Source**: `latitude`, `longitude` + GADM boundaries
- **Transformer**: `LocationTransformer.apply_gadm_boundaries()`
- **Logic**:
  ```
  Derive locality (city/county) from GADM administrative boundaries:

  1. Create point geometry from POI coordinates
  2. Perform spatial join with GADM boundaries
  3. Extract NAME_2 (second-level admin division) as locality
  4. This replaces source locality for accuracy

  Example: Coordinates (34.052, -118.243) -> "Los Angeles"

  Note: Requires GADM_PATH environment variable to be set.
  If GADM boundaries not available, locality will be None.
  ```

#### 13. `inside_establishment_flag`
- **Source**: `inside_places`
- **Transformer**: `EstablishmentTransformer.detect_inside_establishment()`
- **Logic**:
  ```
  If inside_places is non-empty and not null-like -> "yes"
  Otherwise -> "no"
  ```

#### 14. `parent_establishment_name`
- **Source**: `inside_places`
- **Transformer**: `EstablishmentTransformer.extract_parent_name()`
- **Logic**:
  ```
  If inside_places contains comma-separated list:
    Return first name in list
  Otherwise:
    Return inside_places value
  Example: "Mall of America, Level 2" -> "Mall of America"
  ```

#### 15. `parent_establishment_type`
- **Source**: `inside_places_categories`
- **Transformer**: `EstablishmentTransformer.extract_parent_type()`
- **Logic**:
  ```
  Map category keywords to standardized types:
  - "shopping_mall", "shopping_center", "mall" -> "Mall"
  - "airport", "airport_terminal" -> "Airport"
  - "hospital", "medical_center" -> "Hospital"
  - "university", "college", "school" -> "Campus"
  - "hotel", "resort" -> "Hotel"
  - "casino" -> "Casino"
  - "stadium", "arena" -> "Stadium"
  - "convention_center" -> "Convention Center"
  - "train_station", "bus_station", "subway_station" -> "Transit Station"
  - Other -> "Other"
  ```

#### 16. `floor_level`
- **Source**: `floor_no`
- **Transformer**: `EstablishmentTransformer.normalize_floor_level()`
- **Logic**:
  ```
  Normalize to standard format:
  - "ground", "g", "lobby", "0" -> "Ground"
  - "basement", "-1", "-2" -> "B1", "B2"
  - "1", "2", "3" -> "L1", "L2", "L3"
  - Already prefixed (L1, B1) -> uppercase
  ```

#### 17. `price_level`
- **Source**: `price_level` or `price_range`
- **Transformer**: `MetricsTransformer.standardize_price_level()`
- **Logic**:
  ```
  Convert to 1-5 integer scale:

  Dollar sign pattern:
  - "$" -> 1
  - "$$" -> 2
  - "$$$" -> 4
  - "$$$$" -> 5

  Numeric range pattern (extract average):
  - avg < $15 -> 1
  - avg < $25 -> 2
  - avg < $40 -> 3
  - avg < $75 -> 4
  - avg >= $75 -> 5
  ```

#### 18. `average_stay_duration_minutes`
- **Source**: `time_spent`
- **Transformer**: `MetricsTransformer.parse_duration_minutes()`
- **Logic**:
  ```
  Parse duration strings to minutes:
  - "up to 3 hours" -> 180
  - "30 min to 1 hour" -> 60 (uses max)
  - "1-2 hours" -> 120 (uses max)
  - "30 minutes" -> 30

  Regex patterns:
  - Hours: (\d+(?:\.\d+)?)\s*(?:hour|hr)
  - Minutes: (\d+)\s*(?:minute|min)
  - "up to X hours" takes priority
  ```

#### 19. `traffic_score`
- **Source**: `popular_times_data` or `popular_times_data_kg`
- **Transformer**: `MetricsTransformer.calculate_traffic_score()`
- **Logic**:
  ```
  Calculate average popularity (0-100 scale):

  Schema 1 (processed format):
  {"popular_times": [{"day": "Monday", "avg": 75}, ...]}
  -> Average of all "avg" values

  Schema 2 (raw format):
  {"Sunday": [..., {"average_popularity": X}, ...], ...}
  -> Extract average_popularity from index -3 for each day
  -> Average across all days

  Result rounded to 2 decimal places
  ```

#### 20. `status_change`
- **Source**: `oldest_date`, `business_status`, multi-version comparison
- **Transformer**: `StatusTransformer.determine_status_change()`
- **Logic**:
  ```
  Determine if POI opened or closed this month:

  1. Based on oldest_date:
     - If oldest_date month = processing month AND status is "Open" -> "Opened this month"

  2. Based on consecutive version comparison:
     - Compare POI status between version N and version N+1
     - If status changed from "Open" to "Closed"/"Temporarily Closed" -> "Closed this month"
     - If status changed from "Closed" to "Open" -> "Recently Opened"

  Note: New POIs appearing in current version are NOT automatically marked as opened.
  Only POIs with oldest_date matching the processing month get "Opened this month".

  Multi-version processing:
  - Pipeline processes versions chronologically
  - Each consecutive pair is compared for status changes
  - Set PATHS_CSV environment variable to use a CSV with S3 paths
  ```

#### 21. `open_date`
- **Source**: `oldest_date`
- **Transformer**: `StatusTransformer.parse_open_date()`
- **Logic**:
  ```
  Parse oldest_date field to YYYY-MM-DD format.
  This is the sole source for open_date (no multi-month history aggregation).

  Supported formats:
  - YYYY-MM-DD
  - YYYY-MM-DDTHH:MM:SS
  - DD-MM-YYYY
  - MM/DD/YYYY
  ```

#### 22. `closed_date`
- **Source**: Multi-version comparison
- **Transformer**: `StatusTransformer.compare_versions()`
- **Logic**:
  ```
  Determined by comparing consecutive dataset versions.
  Set when a POI's status changes from "Open" to "Closed" or "Temporarily Closed".
  ```

#### 23. `last_verified_date`
- **Source**: `day_time`
- **Transformer**: `StatusTransformer.parse_date()`
- **Logic**:
  ```
  Parse date from day_time field to YYYY-MM-DD
  Supported formats:
  - YYYY-MM-DD
  - YYYY-MM-DDTHH:MM:SS
  - DD-MM-YYYY
  - MM/DD/YYYY

  Fallback: Current date if unparseable
  ```

#### 24. `data_version_month`
- **Source**: Filename pattern
- **Transformer**: `QualityTransformer.extract_month_from_filename()`
- **Logic**:
  ```
  Extract from filename: "United States/20250509/..."
  Regex: (\d{8}) -> extract YYYYMMDD
  Result: "2025-05" (YYYY-MM format)
  ```

#### 25. `verification_confidence_score`
- **Source**: Multiple fields
- **Transformer**: `QualityTransformer.calculate_confidence_score()`
- **Logic**:
  ```
  Weighted scoring (0-100):
  - Has name: +10
  - Has valid coordinates: +15
  - Has address: +10
  - Has phone: +10
  - Has website: +5
  - Has category: +10
  - Has rating: +5
  - Has reviews (>0): +5
  - Has hours: +5
  - Name quality (not numeric/coordinates): +10
  - Address quality (no HTTP, >10 chars): +10
  - Phone valid (passes phonenumbers validation): +5

  Total capped at 100
  ```

#### 26. `data_quality_flag`
- **Source**: `is_claimed`, `rating_count`, `review_count`
- **Transformer**: `QualityTransformer.assess_data_quality()`
- **Logic**:
  ```
  Based on verification signals:

  - "Clean": is_claimed = true AND rating_count > 5 AND review_count > 3
  - "Needs Review": rating_count >= 1 OR is_claimed = true
  - "Low Confidence": Everything else (no reviews, not claimed)
  ```

#### 27. `phone` (validated)
- **Source**: `phone`
- **Transformer**: `QualityTransformer.validate_phone()`
- **Logic**:
  ```
  Validate using phonenumbers library:
  1. Parse phone string (auto-detect country)
  2. Validate number format
  3. If valid -> return original
  4. If invalid -> None
  ```

#### 28. `review_count`
- **Source**: `reviews`
- **Transformer**: `QualityTransformer.extract_review_count()`
- **Logic**:
  ```
  Extract count from reviews JSON:

  Input format:
  {'reviews': [...], 'summary': {'count': 8, 'avg_rating': 3.75, ...}}

  1. Try to get count from summary.count
  2. Fallback: count length of reviews list
  3. If unparseable -> None
  ```

#### 29. `open_hours`
- **Source**: `open_hours`
- **Transformer**: `QualityTransformer.reformat_open_hours()`
- **Logic**:
  ```
  Reformat from complex JSON to simpler format:

  Input format:
  {
    "Sunday": {"intervals": [{"start": "11:00", "end": "18:00"}], "is_24h": false, "closed": false},
    ...
  }

  Output format (simpler JSON):
  {"Mon": "11:00-18:00", "Tue": "11:00-18:00", ..., "Sun": "Closed"}

  Rules:
  - is_24h = true -> "24 hours"
  - closed = true -> "Closed"
  - Multiple intervals joined with ", "
  - Days abbreviated (Mon, Tue, Wed, Thu, Fri, Sat, Sun)
  ```

---

## Project Structure

```
Data-cleaning/
├── usa_poi_pipeline.py      # Main pipeline orchestrator
├── extended_data_pipeline.py # Legacy monolithic script (reference)
├── config/
│   └── schema_mapping.py    # Column mappings and constants
├── transformers/
│   ├── __init__.py
│   ├── core_transformers.py       # POI ID, name, brand detection
│   ├── location_transformers.py   # Coordinates, addresses, postcodes
│   ├── category_transformers.py   # Category hierarchy, dining type
│   ├── status_transformers.py     # Status normalization, date tracking
│   ├── metrics_transformers.py    # Price, duration, traffic, reviews
│   ├── establishment_transformers.py # Parent location detection
│   ├── quality_transformers.py    # Quality scoring, verification
│   └── data_loaders.py            # Config file loaders
└── data/
    ├── branding_usa_configs.csv   # Brand matching config
    ├── xmap_poi_categorization.csv # Category mapping
    └── usa_admin.geojson          # GADM boundaries (optional)
```

---

## Installation

```bash
# Clone repository
git clone <repository-url>
cd Data-cleaning

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your AWS credentials
```

---

## Usage

### Single Run (Auto-discover files)
```bash
# Run the pipeline
python usa_poi_pipeline.py
```

### Multi-Version Processing (from CSV)
```bash
# Create a CSV file with S3 paths (paths.csv):
# Path
# "United States/20250114/United States.zip"
# "United States/20250202/United States.zip"
# ...

# Set environment variable and run
export PATHS_CSV=paths.csv
python usa_poi_pipeline.py
```

---

## Configuration

Required environment variables (`.env`):

```
aws_access_key_id=YOUR_ACCESS_KEY
aws_secret_access_key=YOUR_SECRET_KEY
aws_region_name=us-east-1
s3_bucket_name=your-bucket-name

# Optional
GADM_PATH=data/usa_admin.geojson
CATEGORY_MAPPING_PATH=data/xmap_poi_categorization.csv
BRAND_CONFIG_PATH=data/branding_usa_configs.csv
PATHS_CSV=paths.csv  # For multi-version processing
```

---
