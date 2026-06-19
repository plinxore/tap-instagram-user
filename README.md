# tap-instagram-user

`tap-instagram-user` is a Singer tap for the Meta Graph API (Instagram Insights), built with the [Meltano Singer SDK](https://sdk.meltano.com).

It extracts Instagram insights metrics (`views`, `reach`, `impressions`, ...) day by day, following an ELT strategy: no business transformation is applied by the tap, the raw API response is stored in a `raw_data` column (JSON), alongside metadata (`ig_user_id`, `metric_name`, `breakdown_type`, `metric_date`, `extraction_date`).

## Installation

```bash
uv sync
```

## Configuration

### Main settings

| Setting | Required | Description |
|---|---|---|
| `access_token` | yes | Long-Lived Meta Token for the professional Instagram account |
| `ig_user_id` | yes | Professional Instagram account ID |
| `metrics` | yes | List of metrics (and their breakdowns) to extract — see below |
| `start_date` | no | Start date on first extraction. If absent, computed automatically (1st of the current month minus 12 months) |
| `days_to_subtract` | no (default `0`) | Overlap window: number of already-covered days to re-extract on each run (useful because Meta insights can still be corrected after the fact) |
| `period` | no (default `"day"`) | Granularity requested from the Meta Insights API |
| `timeframe` | no | Optional `timeframe` parameter passed to the API |
| `metric_type` | no (default `"total_value"`) | `metric_type` parameter passed to the API |
| `generate_dates_range` | no (default `"active"`) | `"active"` = one API call per day; `"inactive"` = a single call covering the whole range |

### `metrics`

Each entry defines a metric and generates one stream per metric/breakdown combination (e.g. `views` + `follow_type` -> stream `ig_views_by_follow_type`). An entry may override any of the settings above (except `access_token`/`ig_user_id`, always global) for itself only:

```json
{
  "metrics": [
    {
      "metric": "views",
      "breakdowns": ["follow_type,media_product_type", "follow_type", "media_product_type"]
    },
    {
      "metric": "reach",
      "breakdowns": [""],
      "days_to_subtract": 2,
      "start_date": "2026-01-01T00:00:00Z"
    },
    {
      "metric": "impressions",
      "breakdowns": ["media_product_type"],
      "generate_dates_range": "inactive",
      "period": "week",
      "timeframe": "last_30_days"
    }
  ]
}
```

See [config.template.json](config.template.json) for a full example.

### Configuration via environment variables

Copy `.env.example` to `.env` and fill in the real values (never committed). Meltano convention: `<PLUGIN_NAME>_<SETTING_NAME>` in uppercase, e.g. `TAP_INSTAGRAM_USER_ACCESS_TOKEN`.

The full list of settings is available via:

```bash
tap-instagram-user --about
```

## Usage

### Direct CLI (without Meltano)

```bash
tap-instagram-user --config config.json --discover > catalog.json
tap-instagram-user --config config.json --catalog catalog.json --state state.json
```

### Via Meltano (recommended)

```bash
# Install the Meltano CLI (if not already done)
pipx install meltano

# Install the plugins declared in meltano.yml
meltano install

# Check the config
meltano config tap-instagram-user list
meltano config test tap-instagram-user

# Run the pipeline (extract -> load into Postgres)
meltano run tap-instagram-user target-postgres
```

Meltano automatically manages state (bookmarks) between runs via its own system database — no need to manually handle a `state.json` file.

## Development

### Tests

```bash
uv run pytest
```

### Notable implementation details

- **Bookmark**: based on each day partition's `until`, capped so it never regresses (notably during the monthly consolidation). A single bookmark per stream (`state_partitioning_keys = []`), not one per partition.
- **Primary key**: includes `metric_date` (the day the data is for) in addition to `ig_user_id`/`metric_name`/`breakdown_type`, to prevent an upsert on the target side from overwriting another day's data.
- **Monthly consolidation**: on the 1st of the month, the tap automatically re-extracts the entire month before last (Meta insights can still be corrected after publication).

See the code in [tap_instagram_user/streams.py](tap_instagram_user/streams.py) and [tap_instagram_user/client.py](tap_instagram_user/client.py) for details.

### SDK Dev Guide

See the [Meltano Singer SDK dev guide](https://sdk.meltano.com/en/latest/dev_guide.html) for more information.
