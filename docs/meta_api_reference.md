# Meta API reference (validated against the live API)

Generated: `2026-06-24T17:39:05.024345+00:00` · API `v22.0`.
Regenerate with `python scripts/introspect.py`. ✅ valid · ❌ deprecated/gone · — not supported for this type · ⚠️ other error (see note).

## `ig_user` fields — `GET /{ig_user_id}`
[doc](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user)

| Field | Status | Note |
|---|---|---|
| `biography` | ✅ |  |
| `followers_count` | ✅ |  |
| `follows_count` | ✅ |  |
| `has_profile_pic` | ✅ |  |
| `id` | ✅ |  |
| `is_published` | ✅ |  |
| `legacy_instagram_user_id` | ✅ |  |
| `media_count` | ✅ |  |
| `name` | ✅ |  |
| `profile_picture_url` | ✅ |  |
| `username` | ✅ |  |
| `website` | ✅ |  |

## `ig_media` fields — `GET /{ig_media_id}`
[doc](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media)

| Field | Status | Note |
|---|---|---|
| `id` | ✅ |  |
| `timestamp` | ✅ |  |
| `media_type` | ✅ |  |
| `media_product_type` | ✅ |  |
| `caption` | ✅ |  |
| `permalink` | ✅ |  |
| `like_count` | ✅ |  |
| `comments_count` | ✅ |  |
| `media_url` | ✅ |  |
| `thumbnail_url` | ✅ |  |
| `owner` | ✅ |  |
| `shortcode` | ✅ |  |
| `username` | ✅ |  |
| `is_comment_enabled` | ✅ |  |
| `is_shared_to_feed` | ✅ |  |
| `media_audio_type` | ✅ |  |
| `alt_text` | ✅ |  |
| `boost_ads_list` | ✅ |  |
| `boost_eligibility_info` | ✅ |  |
| `legacy_instagram_media_id` | ✅ |  |
| `total_comments_count` | ✅ |  |
| `total_like_count` | ✅ |  |
| `total_views_count` | ✅ |  |
| `saved_count` | ✅ |  |
| `shares_count` | ✅ |  |
| `reposts_count` | ✅ |  |
| `view_count` | ⚠️ | (#36104) You do not have permission to access this field outside of the Business Discovery API. |

## `ig_user_insights` metrics — `GET /{ig_user_id}/insights`
[doc](https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights)

**Authoritative live metric list (from the API itself):** `reach`, `follower_count`, `website_clicks`, `profile_views`, `online_followers`, `accounts_engaged`, `total_interactions`, `likes`, `comments`, `shares`, `saves`, `replies`, `engaged_audience_demographics`, `reached_audience_demographics`, `follower_demographics`, `follows_and_unfollows`, `profile_links_taps`, `views`, `threads_likes`, `threads_replies`, `reposts`, `quotes`, `threads_followers`, `threads_follower_demographics`, `content_views`, `threads_views`, `threads_clicks`, `threads_reposts`

_Validation of our candidates (period=day, metric_type=total_value):_

| Metric | Status | Note |
|---|---|---|
| `reach` | ✅ |  |
| `likes` | ✅ |  |
| `saves` | ✅ |  |
| `shares` | ✅ |  |
| `replies` | ✅ |  |
| `reposts` | ✅ |  |
| `total_interactions` | ✅ |  |
| `follows_and_unfollows` | ✅ |  |
| `profile_links_taps` | ✅ |  |
| `accounts_engaged` | ✅ |  |
| `profile_visits` | ⚠️ | (#100) metric[0] must be one of the following values: reach, follower_count, website_clicks, profile_views, online_followers, accounts_engaged, total_interactions, likes, comments, shares, saves, replies, engaged_audience_demographics, reached_audience_demographics, follower_demographics, follows_and_unfollows, profile_links_taps, views, threads_likes, threads_replies, reposts, quotes, threads_followers, threads_follower_demographics, content_views, threads_views, threads_clicks, threads_reposts |
| `views` | ✅ |  |
| `impressions` | ⚠️ | (#100) metric[0] must be one of the following values: reach, follower_count, website_clicks, profile_views, online_followers, accounts_engaged, total_interactions, likes, comments, shares, saves, replies, engaged_audience_demographics, reached_audience_demographics, follower_demographics, follows_and_unfollows, profile_links_taps, views, threads_likes, threads_replies, reposts, quotes, threads_followers, threads_follower_demographics, content_views, threads_views, threads_clicks, threads_reposts |

## `ig_media_insights` metrics by media_type — `GET /{ig_media_id}/insights`
[doc](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)

**Authoritative live metric list (from the API itself):** `impressions`, `reach`, `replies`, `saved`, `likes`, `comments`, `shares`, `total_interactions`, `follows`, `profile_visits`, `profile_activity`, `navigation`, `ig_reels_video_view_total_time`, `ig_reels_avg_watch_time`, `views`, `reels_skip_rate`, `reposts`, `facebook_views`, `crossposted_views`, `total_views`, `total_likes`, `total_comments`, `link_clicks`

| Metric | VIDEO | CAROUSEL_ALBUM | IMAGE |
|---|---|---|---|
| `reach` | ✅ | ✅ | ✅ |
| `views` | ✅ | ✅ | ✅ |
| `comments` | ✅ | ✅ | ✅ |
| `likes` | ✅ | ✅ | ✅ |
| `saved` | ✅ | ✅ | ✅ |
| `shares` | ✅ | ✅ | ✅ |
| `reposts` | ✅ | ✅ | ✅ |
| `total_interactions` | ✅ | ✅ | ✅ |
| `profile_activity` | — | ✅ | ✅ |
| `profile_visits` | — | ✅ | ✅ |
| `follows` | — | ✅ | ✅ |
| `navigation` | — | — | — |
| `replies` | — | — | — |
| `link_clicks` | — | — | — |
| `facebook_views` | ⚠️ | ⚠️ | ⚠️ |
| `crossposted_views` | ⚠️ | — | — |
| `ig_reels_avg_watch_time` | ✅ | — | — |
| `ig_reels_video_view_total_time` | ✅ | — | — |
| `reels_skip_rate` | ✅ | — | — |
| `total_comments` | ✅ | ✅ | ✅ |
| `total_likes` | ✅ | ✅ | ✅ |
| `total_views` | ✅ | ✅ | ✅ |
| `impressions` | — | ⚠️ | ⚠️ |
