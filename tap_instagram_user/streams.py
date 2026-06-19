"""Stream type classes for tap-instagram-user."""
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta

from typing import Any, Iterable, Optional
import requests

from singer_sdk import typing as th

from tap_instagram_user.client import InstagramUserStream

class MetaRawInsightsStream(InstagramUserStream):
    """Flux générique pour extraire n'importe quelle métrique Instagram."""

    # `metric_date` (le jour des données, = "since" de la partition) est requis
    # dans la clé : sans lui, deux jours différents de la même métrique
    # s'écrasent mutuellement lors d'un upsert côté target.
    primary_keys = ["ig_user_id", "metric_name", "breakdown_type", "metric_date"]

    replication_key = "extraction_date"
    is_sorted = False
    # Un seul bookmark par stream (et non un par partition since/until), pour que
    # get_context_state(None) dans `partitions` ci-dessous retrouve un bookmark
    # global plutôt qu'un par partition.
    state_partitioning_keys = []

    @staticmethod
    def _build_range_partitions(start: date, end: date, day_by_day: bool) -> list[dict]:
        """Découpe [start, end] (inclus) en partitions since/until.

        Si `day_by_day` est True (mode "active", legacy par défaut) : une
        partition par jour. Sinon (mode "inactive") : une seule partition
        couvrant tout l'intervalle en un seul appel API.
        """
        if start > end:
            return []
        if not day_by_day:
            return [{
                "since": start.strftime("%Y-%m-%d"),
                "until": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
            }]
        partitions = []
        current = start
        while current <= end:
            partitions.append({
                "since": current.strftime("%Y-%m-%d"),
                "until": (current + timedelta(days=1)).strftime("%Y-%m-%d")
            })
            current += timedelta(days=1)
        return partitions

    @property
    def partitions(self) -> list[dict] | None:
        """Génère les tranches d'extraction (Logique Legacy)."""
        partitions = []
        today = date.today()
        days_to_subtract = self.get_param("days_to_subtract", 0)
        # "active" = découpage jour par jour ; "inactive" = un seul appel
        # couvrant toute la plage since/until.
        day_by_day = self.get_param("generate_dates_range", "active") != "inactive"

        # get_starting_replication_key_value() ne convient pas ici : cette méthode
        # lit "starting_replication_value", un champ que le SDK n'écrit qu'après
        # avoir évalué `partitions` (donc toujours vide à ce stade). Le bookmark
        # persisté du run précédent est lu directement via "replication_key_value".
        state_bookmark = self.get_context_state(None).get("replication_key_value")

        if state_bookmark:
            # Garde uniquement les 10 premiers caractères (YYYY-MM-DD) du signet,
            # ex: "2026-06-18T18:39..." -> "2026-06-18".
            last_date_executes = date.fromisoformat(state_bookmark[:10])
            self.logger.info(f"Reprise depuis le signet (State) : {last_date_executes}")
        else:
            # Première exécution : utilise la config, sinon une valeur par défaut.
            start_date_str = self.get_param("start_date")
            if start_date_str:
                last_date_executes = date.fromisoformat(start_date_str[:10])
                self.logger.info(f"Première exécution, démarrage forcé à : {last_date_executes}")
            else:
                # Pas de 'start_date' fournie : repli sur le 1er jour du mois en
                # cours, moins 12 mois (ex: exécution le 19/06/2026 -> 01/06/2025).
                last_date_executes = today.replace(day=1) - relativedelta(months=12)
                self.logger.info(
                    "Première exécution, aucune 'start_date' fournie : valeur par "
                    f"défaut calculée (1er du mois - 12 mois) = {last_date_executes}"
                )

        # Bookmark tel qu'il était au début de cette run. La consolidation
        # ci-dessous génère des partitions avec un "until" antérieur à ce
        # bookmark ; sans ce plancher, le SDK prendrait le max des
        # "extraction_date" vus dans cette run uniquement (cf. parse_response)
        # et ferait régresser le bookmark si le bloc "récent" est vide.
        self._run_start_bookmark = datetime(
            last_date_executes.year, last_date_executes.month, last_date_executes.day,
            tzinfo=timezone.utc,
        )

        if last_date_executes >= today:
            self.logger.info("Le script a déjà été exécuté aujourd'hui. Fin.")
            return []

        # Consolidation du 1er du mois : les insights Meta peuvent encore se
        # corriger après publication, donc l'avant-dernier mois est ré-extrait
        # en entier à chaque début de mois.
        if last_date_executes.day == 1:
            self.logger.info("Début du mois : consolidation de l'avant-dernier mois.")
            first_day_in_2_last_month = (last_date_executes - relativedelta(months=2)).replace(day=1)
            last_day_in_2_last_month = first_day_in_2_last_month + relativedelta(months=1) - timedelta(days=1)

            partitions.extend(self._build_range_partitions(
                first_day_in_2_last_month, last_day_in_2_last_month, day_by_day,
            ))

        # Extraction des jours récents non encore couverts.
        start_recent = last_date_executes - timedelta(days=days_to_subtract)
        end_recent = today - timedelta(days=1)

        partitions.extend(self._build_range_partitions(start_recent, end_recent, day_by_day))

        return partitions

    # Schéma hybride : métadonnées structurées + données brutes en JSONB.
    schema = th.PropertiesList(
        th.Property("ig_user_id", th.StringType, required=True),
        th.Property("metric_name", th.StringType),
        th.Property("breakdown_type", th.StringType),
        # Jour métier des données extraites (= "since" de la partition).
        th.Property("metric_date", th.DateType, required=True),
        th.Property("extraction_date", th.DateTimeType),
        th.Property(
            "raw_data", 
            th.CustomType({"type": ["object", "array"]}), 
            description="Le JSON brut renvoyé par l'API Meta"
        )
    ).to_dict()

    def __init__(
        self,
        tap: Any,
        name: str,
        metric_name: str,
        breakdown: Optional[str] = None,
        start_date: Optional[str] = None,
        days_to_subtract: Optional[int] = None,
        period: Optional[str] = None,
        timeframe: Optional[str] = None,
        metric_type: Optional[str] = None,
        generate_dates_range: Optional[str] = None,
        **kwargs
    ):
        """Initialisation dynamique du flux.

        `start_date`, `days_to_subtract`, `period`, `timeframe`, `metric_type` et
        `generate_dates_range` sont des surcharges optionnelles définies au niveau
        de l'entrée `metrics` correspondante (cf. tap.py). Si non fournies (None),
        `get_param()` (cf. client.py) retombe sur la valeur globale du tap.
        """
        super().__init__(tap=tap, name=name, **kwargs)

        self.metric_name = metric_name
        self.breakdown = breakdown
        self._override_start_date = start_date
        self._override_days_to_subtract = days_to_subtract
        self._override_period = period
        self._override_timeframe = timeframe
        self._override_metric_type = metric_type
        self._override_generate_dates_range = generate_dates_range

        self.path = f"/{self.config.get('ig_user_id')}/insights"

    def get_records(self, context: Optional[dict]) -> Iterable[dict]:
        """Aucune partition à traiter = aucun appel API.

        `partitions` retourne [] quand il n'y a rien à extraire (déjà exécuté
        aujourd'hui, pas de start_date, ...). Mais pour le SDK, une liste de
        partitions vide est "falsy" et retombe sur un contexte {} unique
        (cf. `context_list or [{}]` dans core.py), ce qui déclencherait un appel
        API sans since/until. On bloque explicitement ce cas ici.
        """
        if not context:
            return
        yield from super().get_records(context)

    def parse_response(self, response: requests.Response) -> Iterable[dict]:
        """Enveloppe la réponse brute de Meta avec ses métadonnées, sans transformation."""
        # Le "until" de la partition courante (posé par get_url_params dans
        # client.py) sert de valeur de bookmark : il représente le jour suivant
        # la dernière journée de données réellement couverte, pas l'heure
        # d'exécution. Il est plafonné par le bookmark de début de run pour que
        # les partitions de consolidation (dates passées) ne fassent jamais
        # reculer le signet.
        current_until = getattr(self, "_current_until", None)
        run_start_bookmark = getattr(self, "_run_start_bookmark", None)
        if current_until and run_start_bookmark:
            bookmark_value = max(current_until, run_start_bookmark)
        else:
            bookmark_value = current_until or datetime.now(timezone.utc)
        current_since = getattr(self, "_current_since", None)

        yield {
            "ig_user_id": self.config.get("ig_user_id"),
            "metric_name": self.metric_name,
            "breakdown_type": self.breakdown if self.breakdown else "none",
            "metric_date": current_since.date().isoformat() if current_since else None,
            "extraction_date": bookmark_value.isoformat(), # La valeur qui sera sauvegardée par le SDK
            "raw_data": response.json()
        }