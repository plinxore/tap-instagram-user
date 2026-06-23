"""REST client handling, including InstagramUserStream base class."""

from datetime import datetime, timezone
from typing import Any

from singer_sdk.helpers.types import Context
from singer_sdk.streams import RESTStream


class InstagramUserStream(RESTStream):
    """Base class handling the connection to the Meta Graph API.

    No static JSON schema and no JSONPath parser: the schema and response
    parsing are entirely dynamic (cf. UserInsightsStream).
    """

    @property
    def url_base(self) -> str:
        """Return the Meta API root URL (version 22.0)."""
        return "https://graph.facebook.com/v22.0"

    def get_param(self, name: str, default: Any = None) -> Any:
        """Return a config parameter, overridable per metric.

        If the stream was instantiated with an override for `name` (cf.
        UserInsightsStream.__init__, attribute `_override_<name>`), it is
        returned; otherwise the tap's global value (`config.json`) applies.
        """
        override = getattr(self, f"_override_{name}", None)
        if override is not None:
            return override
        return self.config.get(name, default)

    def get_url_params(
        self, context: Context | None, next_page_token: Any | None
    ) -> dict[str, Any]:
        """Build the request parameters (querystring) for the Meta API."""
        params: dict = {}

        params["access_token"] = self.config.get("access_token")

        if hasattr(self, "metric_name") and self.metric_name:
            params["metric"] = self.metric_name
            # metric_type is always sent (default value "total_value") for
            # every metric, overridable per entry in `metrics`.
            params["metric_type"] = self.get_param("metric_type", "total_value")

        if hasattr(self, "breakdown") and self.breakdown:
            params["breakdown"] = self.breakdown

        params["period"] = self.get_param("period", "day")
        if self.get_param("timeframe"):
            params["timeframe"] = self.get_param("timeframe")

        if context and "since" in context and "until" in context:
            # since/until are "YYYY-MM-DD" dates in the partition context;
            # the Meta API expects UNIX timestamps.
            since_dt = datetime.strptime(context["since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until_dt = datetime.strptime(context["until"], "%Y-%m-%d").replace(tzinfo=timezone.utc)

            params["since"] = int(since_dt.timestamp())
            params["until"] = int(until_dt.timestamp())

            # Kept for parse_response (cf. streams.py): "until" is used as
            # the bookmark value, "since" as the business date (primary key).
            self._current_since = since_dt
            self._current_until = until_dt

        if next_page_token:
            params["after"] = next_page_token

        return params
