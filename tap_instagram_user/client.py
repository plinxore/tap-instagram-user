"""REST client handling, including InstagramUserStream base class."""

from datetime import datetime, timedelta, timezone

from typing import Any, Dict, Optional
from singer_sdk.streams import RESTStream

class InstagramUserStream(RESTStream):
    """Classe de base gérant la connexion à l'API Meta Graph."""

    # On n'utilise pas de schémas JSON statiques (tout est dynamique)
    # On n'utilise pas non plus le parseur JSONPath par défaut.

    @property
    def url_base(self) -> str:
        """Retourne l'URL racine de l'API Meta (Version 22.0)."""
        return "https://graph.facebook.com/v22.0"

    def get_param(self, name: str, default: Any = None) -> Any:
        """Renvoie un paramètre de config, surchargeable par métrique.

        Si le stream a été instancié avec une surcharge pour `name` (cf.
        MetaRawInsightsStream.__init__, attribut `_override_<name>`), on la
        retourne ; sinon on retombe sur la valeur globale du tap (`config.json`).
        """
        override = getattr(self, f"_override_{name}", None)
        if override is not None:
            return override
        return self.config.get(name, default)

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        """
        Définit les paramètres (querystring) ajoutés à la fin de l'URL.
        """
        params: dict = {}
        
        # --- Auth et Métriques ---
        params["access_token"] = self.config.get("access_token")

        if hasattr(self, "metric_name") and self.metric_name:
            params["metric"] = self.metric_name
            # Comportement legacy : metric_type est toujours envoyé (valeur par
            # défaut "total_value"), pour toutes les métriques. Surchageable par
            # entrée dans `metrics` au besoin.
            params["metric_type"] = self.get_param("metric_type", "total_value")

        if hasattr(self, "breakdown") and self.breakdown:
            params["breakdown"] = self.breakdown

        params["period"] = self.get_param("period", "day")
        if self.get_param("timeframe"):
            params["timeframe"] = self.get_param("timeframe")

        # INJECTION DU SAUCISSONNAGE (Avec conversion UNIX absolue)
        if context and "since" in context and "until" in context:
            # 1. On transforme le texte "2026-06-10" en objet date (en forçant l'UTC)
            since_dt = datetime.strptime(context["since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until_dt = datetime.strptime(context["until"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            # 2. On le convertit en entier (Timestamp UNIX) pour l'API Meta
            params["since"] = int(since_dt.timestamp())
            params["until"] = int(until_dt.timestamp())

            # On garde le "until" de la partition pour pouvoir l'utiliser comme
            # valeur de bookmark dans parse_response (cf. streams.py), et le
            # "since" comme date métier des données extraites (clé primaire).
            self._current_since = since_dt
            self._current_until = until_dt

        if next_page_token:
            params["after"] = next_page_token

        return params