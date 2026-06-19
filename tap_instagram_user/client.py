"""REST client handling, including InstagramUserStream base class."""

from datetime import datetime, timedelta, timezone

from typing import Any, Dict, Optional
from singer_sdk.streams import RESTStream

class InstagramUserStream(RESTStream):
    """Classe de base gérant la connexion à l'API Meta Graph.

    Pas de schéma JSON statique ni de parseur JSONPath : le schéma et le parsing
    de la réponse sont entièrement dynamiques (cf. MetaRawInsightsStream).
    """

    @property
    def url_base(self) -> str:
        """Retourne l'URL racine de l'API Meta (Version 22.0)."""
        return "https://graph.facebook.com/v22.0"

    def get_param(self, name: str, default: Any = None) -> Any:
        """Renvoie un paramètre de config, surchargeable par métrique.

        Si le stream a été instancié avec une surcharge pour `name` (cf.
        MetaRawInsightsStream.__init__, attribut `_override_<name>`), elle est
        retournée ; sinon la valeur globale du tap (`config.json`) s'applique.
        """
        override = getattr(self, f"_override_{name}", None)
        if override is not None:
            return override
        return self.config.get(name, default)

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """Construit les paramètres de requête (querystring) pour l'API Meta."""
        params: dict = {}

        params["access_token"] = self.config.get("access_token")

        if hasattr(self, "metric_name") and self.metric_name:
            params["metric"] = self.metric_name
            # metric_type est toujours envoyé (valeur par défaut "total_value"),
            # pour toutes les métriques, surchageable par entrée dans `metrics`.
            params["metric_type"] = self.get_param("metric_type", "total_value")

        if hasattr(self, "breakdown") and self.breakdown:
            params["breakdown"] = self.breakdown

        params["period"] = self.get_param("period", "day")
        if self.get_param("timeframe"):
            params["timeframe"] = self.get_param("timeframe")

        if context and "since" in context and "until" in context:
            # since/until sont des dates "YYYY-MM-DD" dans le contexte de
            # partition ; l'API Meta attend des timestamps UNIX.
            since_dt = datetime.strptime(context["since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until_dt = datetime.strptime(context["until"], "%Y-%m-%d").replace(tzinfo=timezone.utc)

            params["since"] = int(since_dt.timestamp())
            params["until"] = int(until_dt.timestamp())

            # Conservés pour parse_response (cf. streams.py) : "until" sert de
            # valeur de bookmark, "since" de date métier (clé primaire).
            self._current_since = since_dt
            self._current_until = until_dt

        if next_page_token:
            params["after"] = next_page_token

        return params