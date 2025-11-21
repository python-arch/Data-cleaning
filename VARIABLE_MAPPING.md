# Variable Mapping Guide

How each output field is created from the source data.

## Quick Stats

| Status | Count |
|--------|-------|
| Implemented | 32 |
| Output Fields | 38 |

---

## Required Schema

The pipeline enforces strict schema validation. Files must have exact column names.

### Input Data (POI)

Required columns:
- `google_id` - Unique identifier
- `name` - Business name
- `latitude` - Coordinate
- `longitude` - Coordinate

### Brand Config File

Required columns: `name`, `website_domain`, `brand_name`

```csv
name,website_domain,brand_name
starbucks,starbucks.com,Starbucks
mcdonald's,mcdonalds.com,McDonald's
```

### Category Mapping File

Required columns: `original_category`, `meta_category`, `middle_category`, `target_category`

```csv
original_category,meta_category,middle_category,target_category
restaurant,Food & Beverage,Restaurants & Eateries,Restaurant
```

---

## Core Fields

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `poi_id` | `google_id` | MD5 hash for uniqueness |
| `name` | `name` | Cleaned (extra spaces removed) |
| `chain_flag` | Derived | Matched against known brands (yes/no) |
| `brand_name` | Derived | Matched from brand config file |

---

## Categories

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `category_level_1` | `category_main` | Top-level (e.g., "Food & Beverage") |
| `category_level_2` | `category_main` | Mid-level (e.g., "Restaurants") |
| `category_level_3` | `category_main` | Specific (e.g., "Italian Restaurant") |

---

## Status

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `status` | `business_status` | Simplified to: Open, Closed, or Temporarily Closed |

Mapping:
- `open`, `open 24 hours`, `operational` = **Open**
- `closed`, `permanently closed` = **Closed**
- `closed_temporarily`, `temporarily closed` = **Temporarily Closed**

---

## Location - Coordinates

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `latitude` | `latitude` | Small random noise added for privacy |
| `longitude` | `longitude` | Small random noise added for privacy |

Filtering:
- Records outside continental USA (24-49.5N, 125-66W) are removed
- Invalid or missing coordinates are removed

---

## Location - Address

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `address_full` | `address` | Plus code prefix removed if present |
| `street` | `street` | Direct copy |
| `city` | `locality` | Direct copy (or from GADM boundaries) |
| `state` | `region_level_1` | Direct copy (or from GADM boundaries) |
| `postal_code` | `postcode` | Validated US format, extracted from address if missing |
| `country_code` | `country` | Direct copy |
| `country_isocode` | `country` | Direct copy |

---

## Inside Establishment

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `inside_establishment_flag` | `inside_places` | "yes" if POI is inside another place |
| `parent_establishment_name` | `inside_places` | Name of the parent location |
| `parent_establishment_type` | `inside_places_categories` | Type of parent (Mall, Airport, etc.) |
| `floor_level` | `floor_no` | Normalized format (L1, B1, Ground) |

Parent Types: Mall, Airport, Hospital, Campus, Hotel, Transit Station, Stadium, Casino

---

## Dates & Changes

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `status_change` | Derived | "Opened this month" or "Closed this month" |
| `open_date` | `oldest_date` | When the POI first appeared |
| `closed_date` | Derived | When the POI closed |
| `last_verified_date` | `day_time` | Last data verification date |

---

## Dining & Pricing

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `dining_type` | Derived | Restaurant classification |
| `price_level` | `price_level` or `price_range` | 1-5 scale |

Dining Types:
- **QSR**: Fast food, drive-through, counter service
- **Fine Dining**: Upscale, reservations, high price
- **Family Dining**: Kid-friendly, group-friendly
- **Casual Dining**: Relaxed atmosphere, dine-in

Price Scale:
- 1: Budget ($, under $15)
- 2: Moderate ($$, $15-25)
- 3: Mid-range ($$$, $25-40)
- 4: Upscale ($$$$, $40-75)
- 5: Premium ($$$$$, over $75)

---

## Traffic & Duration

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `average_stay_duration_minutes` | `time_spent` | Converted to minutes |
| `traffic_score` | `popular_times_data` | Weekly average (0-100) |

Duration Examples:
- "up to 3 hours" = 180 minutes
- "30 min to 1 hour" = 60 minutes

---

## Reviews

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `review_count` | `rating_count` | Total number of reviews |
| `average_rating` | `rating` | Average score (0-5) |

---

## Data Quality

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `data_version_month` | Filename | Extracted as YYYY-MM |
| `verification_source` | Derived | Manual, Partner, or Automated |
| `verification_confidence_score` | Derived | Quality score (0-100) |
| `data_quality_flag` | Derived | Clean, Needs Review, or Low Confidence |

Verification Source:
- **Partner**: Business is claimed by owner
- **Manual**: Has detailed description and photos
- **Automated**: Everything else

Quality Score Breakdown:

| Check | Points |
|-------|--------|
| Has name | 10 |
| Valid coordinates | 15 |
| Has address | 10 |
| Has phone | 10 |
| Has website | 5 |
| Has category | 10 |
| Has rating | 5 |
| Has reviews | 5 |
| Has hours | 5 |
| Good name quality | 10 |
| Good address quality | 10 |
| Valid phone format | 5 |

Quality Flags:
- **Clean**: Score 70+
- **Needs Review**: Score 40-69
- **Low Confidence**: Score under 40

---

## Hotel Fields

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `hotel_star_rating` | `hotel_stars` | Direct copy |

---

## Other Fields

| Output Field | Source | How It Works |
|--------------|--------|--------------|
| `website_domain` | `website_domain` | IP addresses removed |
| `phone` | `phone` | Validated format |
| `open_hours` | `open_hours` | Direct copy |

---

## Reference Files

Required configuration files:

1. **`branding_usa_configs.csv`** - Brand/chain detection
   - Required columns: `name`, `website_domain`, `brand_name`

2. **`xmap_poi_categorization.csv`** - Category mapping
   - Required columns: `original_category`, `meta_category`, `middle_category`, `target_category`

3. **`usa_admin.geojson`** - Geographic boundaries (optional)
   - Used to correct city/state from coordinates

---

## Data Filtering

Records are removed if:
- Coordinates are missing or invalid
- Location is outside continental USA
- Name is meaningless (just numbers, coordinates, etc.)
- Duplicate POI ID

---

## Logging

The pipeline uses Python's logging module. Log levels:
- **INFO**: Processing progress, file operations, summary stats
- **DEBUG**: Detailed row counts, transformation details
- **WARNING**: Missing optional data, skipped files
- **ERROR**: Schema validation failures, processing errors

Configure logging:
```python
logger = setup_logging(log_level='INFO', log_file='pipeline.log')
```

---

## Usage Example

```python
from usa_poi_pipeline import USAPOIPipeline, setup_logging

logger = setup_logging(log_level='INFO')

pipeline = USAPOIPipeline(
    s3_client=s3_client,
    s3_bucket_name='your-bucket',
    local_download_path='/tmp/download',
    local_save_path='./output/usa',
    gadm_boundaries=gadm_gdf,       # Optional
    category_mapping_df=cat_df,     # Required schema
    brand_config_df=brand_df,       # Required schema
    logger=logger,
)

pipeline.run()
```

Output: `USA_YYYYMMDD.csv` with all fields populated.

---

## Error Handling

The pipeline raises errors for schema violations:

```python
# Missing brand config columns
ValueError: Brand config file missing required columns: ['website_domain'].
Expected columns: ['name', 'website_domain', 'brand_name'].
Found columns: ['name', 'brand_name']

# Missing category mapping columns
ValueError: Category mapping file missing required columns: ['meta_category'].
Expected columns: ['original_category', 'meta_category', 'middle_category', 'target_category'].

# Missing input data columns
ValueError: Input data missing required columns: ['google_id']
```
