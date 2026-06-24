# tap-instagram-user

`tap-instagram-user` is a Singer tap for the Meta Graph API (Instagram): account-level (user) insights **and** media (posts) with their per-post insights, built with the [Meltano Singer SDK](https://sdk.meltano.com).

> **About the name:** despite the `-user` suffix (the tap started with the IG User node), it covers multiple Instagram Graph nodes — currently the **User** node (account insights) and the **Media** node (posts + per-post insights) — and is structured to add more.

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
| `start_date` | on first run | Start date on first extraction (ignored once a bookmark exists). No default — required on a stream's first run, settable globally or per metric |
| `days_to_subtract` | no (default `0`) | Overlap window: number of already-covered days to re-extract on each run (useful because Meta insights can still be corrected after the fact) |
| `period` | no (default `"day"`) | Granularity requested from the Meta Insights API |
| `timeframe` | no | Optional `timeframe` parameter passed to the API |
| `metric_type` | no (default `"total_value"`) | `metric_type` parameter passed to the API |
| `generate_dates_range` | no (default `"active"`) | `"active"` = one API call per day; `"inactive"` = a single call covering the whole range |
| `user_fields` | no | Fields of the IG User node (e.g. `followers_count`, `media_count`, `username`). Set to enable the `ig_user` account-profile snapshot stream (`GET /{ig_user_id}`); omit to skip it. No default. |

### `metrics`

Each entry defines a metric and generates one stream per metric/breakdown combination (e.g. `views` + `follow_type` -> stream `ig_user_insights_views_by_follow_type`; `reach` with no breakdown -> `ig_user_insights_reach`). An entry may override any of the settings above (except `access_token`/`ig_user_id`, always global) for itself only:

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

### Media extraction (optional)

In addition to account-level (user) insights, the tap can extract **media** (posts) and their **per-post insights**. This is opt-in: media streams are only discovered when `media_fields` is set, so user-only setups are unaffected.

Two levels, mirroring the Meta API:

- **`ig_media`** — the account's media list (`GET /{ig_user_id}/media`), cursor-paginated. One row per post per day (snapshot), raw post JSON stored in `raw_data`.
- **`ig_media_insights_<metric>`** — per-post insights (`GET /{id_post}/insights`), one stream per metric/breakdown (child of `ig_media`). One row per post × metric.

Stream names follow `ig_<node>_<edge>[_<metric>[_by_<breakdown>]]` (e.g. `ig_user_insights_reach`, `ig_media_insights_views`), with the bare node (`ig_media`) for the object list itself. The explicit edge segment keeps names collision-free as more Meta edges are added (e.g. a future `ig_media_comments` edge never clashes with the `comments` insight metric `ig_media_insights_comments`).

| Setting | Required | Description |
|---|---|---|
| `media_fields` | yes (to enable media) | Fields requested on the `/media` edge. No default (Meta-controlled vocabulary). **Must include `media_product_type`** — the insights children use it to filter valid metrics. |
| `media_limit` | no (default `100`) | Page size (`limit`) for `/media` |
| `media_max_pages` | no (default `100`) | Safety cap on pagination |
| `media_since` | no | Floor date for the `/media` list (sent as `since`). Bounds the first-run backfill. No default (omit = whole catalogue, ~10K cap). |
| `media_until` | no | Ceiling date (sent as `until`). Usually unset (= up to now); for backfilling a fixed window. |
| `media_active_window_days` | no | Rolling refresh window (days). When set, only the first run backfills; later runs fetch just the last N days, so frozen old posts aren't re-fetched. Omit for a full snapshot every run. No default (opt-in). |
| `media_metrics` | yes (for insights) | List of per-post metrics (and optional breakdowns), same shape as `metrics` |
| `media_metric_compatibility` | yes (with `media_metrics`) | Maps each `media_product_type` (FEED/REELS/STORY) to its valid metrics. No default. |
| `media_metric_compatibility_by_media_type` | no | Optional second axis: maps each `media_type` (IMAGE/VIDEO/CAROUSEL_ALBUM) to its valid metrics. When set, a metric is requested only if valid for **both** the post's product_type **and** media_type. Requires `media_type` in `media_fields`. |
| `on_unsupported_metric` | no (default `fail`) | When Meta rejects a metric despite the tables: `fail` stops the run (stale-table signal, no silent loss); `skip` logs a WARNING and skips that post/metric (resilient unattended pipelines). |

```json
{
  "media_fields": ["id", "timestamp", "media_type", "media_product_type", "like_count", "comments_count"],
  "media_metrics": [
    { "metric": "reach" },
    { "metric": "views" },
    { "metric": "profile_activity", "breakdowns": ["action_type"] }
  ],
  "media_metric_compatibility": {
    "FEED":  ["reach", "views", "likes", "comments", "profile_activity"],
    "REELS": ["reach", "views", "likes", "comments"],
    "STORY": ["reach", "replies", "navigation"]
  }
}
```

Why `media_metric_compatibility` is config (not hardcoded): Meta only supports certain metrics per media type, and that vocabulary changes over time. Keeping it in config means a Meta change is fixed by editing config, not by republishing the package. At runtime, a metric is requested for a post only if it is in `media_metrics` **and** `media_metric_compatibility[<product_type>]` — and, when `media_metric_compatibility_by_media_type` is set, also in `media_metric_compatibility_by_media_type[<media_type>]` (intersection of the two axes). This second axis captures finer Meta rules the product_type alone can't, e.g. `views` applies to VIDEO media only, so it is skipped on FEED images. If Meta still rejects a metric both tables claim is valid, the behaviour depends on `on_unsupported_metric`: `fail` (default) stops the run loudly (stale-table signal, no silent loss), while `skip` logs a WARNING and skips just that post/metric (resilient unattended pipelines).

User and media streams are independent — run only user insights by selecting only the `ig_user_*` streams (media children additionally depend on the `ig_media` parent at runtime). See `select:` in [meltano.yml](meltano.yml).

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

### API field/metric reference

[`docs/meta_api_reference.md`](docs/meta_api_reference.md) lists every field/metric we know per node/edge, **validated against the live Meta API** (Meta doesn't expose introspection on Instagram nodes, so we test a curated candidate list instead). It's the menu for `user_fields`/`media_fields`/`metrics`, and it surfaces deprecations. For the insights edges it also captures Meta's **authoritative live metric list** (read straight from the API's error message).

Regenerate it anytime (needs a `config.json` with `access_token`/`ig_user_id`):
```bash
python scripts/introspect.py
```
The `git diff` of `docs/meta_api_reference.{md,yaml}` is then the changelog of what Meta added or dropped. Add newly documented items to [`scripts/api_candidates.yaml`](scripts/api_candidates.yaml) when the docs introduce them.

### Tests

```bash
uv run pytest
```

### Notable implementation details

- **Bookmark**: based on each day partition's `until`, capped so it never regresses (notably during the monthly consolidation). A single bookmark per stream (`state_partitioning_keys = []`), not one per partition.
- **Primary key**: includes `metric_date` (the day the data is for) in addition to `ig_user_id`/`metric_name`/`breakdown_type`, to prevent an upsert on the target side from overwriting another day's data.
- **Monthly consolidation**: on the 1st of the month, the tap automatically re-extracts the entire month before last (Meta insights can still be corrected after publication).
- **Media (`ig_media` / `ig_media_insights_<metric>`)**: the per-post insights edge always reports `lifetime`. The `ig_media` parent is cursor-paginated and guarded against running twice the same day; the per-metric children are SDK child streams (`parent_stream_type`) that receive each post's `media_product_type` and only call metrics declared valid for it.
- **Media incremental strategy**: by default `ig_media` is a full daily snapshot. With `media_active_window_days` set, only the first run backfills (down to `media_since`); subsequent runs fetch only `since = min(last_run, today - window)` — a rolling window that refreshes recent posts (whose stats still evolve) and covers any pause, while leaving frozen old posts untouched (so their insights aren't re-fetched). This is the media counterpart of the user-insights monthly consolidation. The driving bookmark is `ig_media`'s `extraction_date` (presence = backfill done; value = last run).

See the code in [tap_instagram_user/streams.py](tap_instagram_user/streams.py) and [tap_instagram_user/client.py](tap_instagram_user/client.py) for details.

### SDK Dev Guide

See the [Meltano Singer SDK dev guide](https://sdk.meltano.com/en/latest/dev_guide.html) for more information.
