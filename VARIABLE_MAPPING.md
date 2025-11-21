# Variable Mapping - USA POI Data Pipeline

This document describes how each target variable is mapped from the source S3 data.

## Summary

| Status | Count |
|--------|-------|
| Fully Implemented | 32 |
| Needs Additional Data | 0 |
| Notes Required | 3 |

---

## Core Identification

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `poi_id` | `google_id` | MD5 hash | ✅ Implemented |
| `name` | `name` | Clean whitespace | ✅ Implemented |
| `chain_flag` | Derived | Brand matching (yes/no) | ✅ Implemented |
| `brand_name` | Derived | Match against brand config | ✅ Implemented |

### Notes:
- `chain_flag` requires `branding_usa_configs.csv` for accurate matching
- Without brand config, all POIs will have `chain_flag = 'no'`

---

## Hierarchical Categories

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `category_level_1` | `category_main` | Map via `meta_category` | ✅ Implemented |
| `category_level_2` | `category_main` | Map via `middle_category` | ✅ Implemented |
| `category_level_3` | `category_main` | Map via `target_category` | ✅ Implemented |

### Notes:
- Requires `xmap_poi_categorization.csv` for mapping
- Without mapping file, categories will be `None`

---

## Status

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `status` | `business_status` | Normalize to Open/Closed/Temporarily Closed | ✅ Implemented |

### Mapping:
- `open`, `open 24 hours`, `operational` → **Open**
- `closed`, `permanently closed` → **Closed**
- `closed_temporarily`, `temporarily closed` → **Temporarily Closed**

---

## Location - Coordinates

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `latitude` | `latitude` | Add 2-digit noise for privacy | ✅ Implemented |
| `longitude` | `longitude` | Add 2-digit noise for privacy | ✅ Implemented |

### Validation:
- Coordinates outside continental USA bounds (24.0-49.5°N, 125.0-66.0°W) are filtered
- Invalid/null coordinates are removed

---

## Location - Address

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `address_full` | `address` | Remove plus code prefix | ✅ Implemented |
| `street` | `street` | Direct mapping | ✅ Implemented |
| `city` | `locality` | Direct mapping (or GADM) | ✅ Implemented |
| `state` | `region_level_1` | Direct mapping (or GADM) | ✅ Implemented |
| `postal_code` | `postcode` | Validate or extract from address | ✅ Implemented |
| `country_code` | `country` | Direct mapping | ✅ Implemented |
| `country_isocode` | `country` | Direct mapping | ✅ Implemented |

### Notes:
- If GADM boundaries file provided, city/state are corrected via spatial join
- Postal codes are validated against US format (5-digit or 5+4)

---

## Inside Establishment

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `inside_establishment_flag` | `inside_places` | Check if not empty (yes/no) | ✅ Implemented |
| `parent_establishment_name` | `inside_places` | Extract first name | ✅ Implemented |
| `parent_establishment_type` | `inside_places_categories` | Map to type | ✅ Implemented |
| `floor_level` | `floor_no` | Normalize (L1, B1, Ground) | ✅ Implemented |

### Parent Type Mapping:
- `shopping_mall`, `shopping_center` → **Mall**
- `airport`, `airport_terminal` → **Airport**
- `hospital`, `medical_center` → **Hospital**
- `university`, `college`, `school` → **Campus**
- `hotel`, `resort` → **Hotel**
- `train_station`, `bus_station`, `subway_station` → **Transit Station**
- `stadium`, `arena` → **Stadium**
- `casino` → **Casino**
- Other → **Other**

---

## Temporal / Status Change

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `status_change` | Derived | Track across months | ✅ Implemented |
| `open_date` | `oldest_date` | Parse date | ✅ Implemented |
| `closed_date` | Derived | Track across months | ✅ Implemented |
| `last_verified_date` | `day_time` | Parse date | ✅ Implemented |

### Notes:
- `status_change`: "Opened this month" or "Closed this month"
- For accurate open/close tracking, process multiple monthly files chronologically
- Edge cases handled: boundary guard, reopening detection

---

## Dining & Pricing

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `dining_type` | Derived | Classify from categories/attributes | ✅ Implemented |
| `price_level` | `price_level` or `price_range` | Standardize to 1-5 | ✅ Implemented |

### Dining Types:
- **QSR**: Fast food chains, drive-through, counter service
- **Fine Dining**: Price level 4-5, upscale atmosphere, reservations
- **Family Dining**: Family-friendly, good for kids/groups
- **Casual Dining**: Casual atmosphere, dine-in

### Price Level Mapping:
- `$` or `<$15` → **1**
- `$$` or `$15-25` → **2**
- `$$$` or `$25-40` → **3** (mapped to 4 in source)
- `$$$$` or `$40-75` → **4**
- `$$$$$` or `>$75` → **5**

---

## Traffic & Duration

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `average_stay_duration_minutes` | `time_spent` | Parse text to minutes | ✅ Implemented |
| `traffic_score` | `popular_times_data` | Calculate weekly average | ✅ Implemented |

### Duration Parsing Examples:
- "People typically spend up to 3 hours here" → **180**
- "People typically spend 30 min to 1 hour" → **60** (uses max)
- "1-2 hours" → **120** (uses max)

### Traffic Score:
- Average of daily popularity scores (0-100)
- Calculated from `popular_times_data` or `popular_times_data_kg`

---

## Reviews

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `review_count` | `rating_count` | Cast to integer | ✅ Implemented |
| `average_rating` | `rating` | Validate 0-5 scale | ✅ Implemented |

---

## Data Quality & Versioning

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `data_version_month` | Filename | Extract YYYY-MM | ✅ Implemented |
| `verification_source` | Derived | Manual/Partner/Automated | ✅ Implemented |
| `verification_confidence_score` | Derived | Calculate 0-100 | ✅ Implemented |
| `data_quality_flag` | Derived | Clean/Needs Review/Low Confidence | ✅ Implemented |

### Verification Source Logic:
- **Partner**: `is_claimed = true`
- **Manual**: Has detailed description AND multiple photos
- **Automated**: Default

### Confidence Score Factors (0-100):
| Factor | Points |
|--------|--------|
| Has name | +10 |
| Has valid coordinates | +15 |
| Has address | +10 |
| Has phone | +10 |
| Has website | +5 |
| Has category | +10 |
| Has rating | +5 |
| Has reviews | +5 |
| Has hours | +5 |
| Quality name (not numeric) | +10 |
| Quality address (not HTTP) | +10 |
| Valid phone format | +5 |

### Quality Flag Thresholds:
- **Clean**: Score ≥ 70
- **Needs Review**: Score 40-69
- **Low Confidence**: Score < 40

---

## Hotel Specific

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `hotel_star_rating` | `hotel_stars` | Direct mapping | ✅ Implemented |

---

## Additional Metadata

| Target Variable | Source Field | Transform | Status |
|-----------------|--------------|-----------|--------|
| `website_domain` | `website_domain` | Validate (remove IPs) | ✅ Implemented |
| `phone` | `phone` | Validate format | ✅ Implemented |
| `open_hours` | `open_hours` | Direct mapping | ✅ Implemented |

---

## Required Reference Files

1. **`branding_usa_configs.csv`** (Optional but recommended)
   - Columns: `name`, `website_domain`, `original_category`, `brand_name`
   - Used for chain/brand detection

2. **`xmap_poi_categorization.csv`** (Optional but recommended)
   - Columns: `original_category`, `target_category`, `middle_category`, `meta_category`
   - Used for category hierarchy mapping

3. **`usa_admin.geojson`** (Optional)
   - GADM administrative boundaries
   - Used for correcting city/state based on coordinates

---

## Data Filtering

Records are removed if:
1. Coordinates are missing or invalid
2. Coordinates are outside continental USA
3. Name is meaningless (pure numbers, coordinates, etc.)
4. Name starts with number/special char (except "7-Eleven")
5. Address contains HTTP
6. Duplicate `poi_id`

---

## Usage

```python
from usa_poi_pipeline import USAPOIPipeline

pipeline = USAPOIPipeline(
    s3_client=s3_client,
    s3_bucket_name='your-bucket',
    local_download_path='/tmp/download',
    local_save_path='./output/usa',
    gadm_boundaries=gadm_gdf,  # Optional
    category_mapping_df=cat_df,  # Optional
    brand_config_df=brand_df,  # Optional
)

pipeline.run()
```

Output files: `USA_YYYYMMDD.csv` with all variables populated.
