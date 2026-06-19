"""Stream type classes for tap-instagram-user."""
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta

from typing import Any, Iterable, Optional
import requests

from singer_sdk import typing as th

# Nous allons corriger le nom de cette classe dans le fichier client.py juste après
from tap_instagram_user.client import InstagramUserStream

class MetaRawInsightsStream(InstagramUserStream):
    """Flux générique pour extraire n'importe quelle métrique Instagram."""

    # On définit la clé composite pour PostgreSQL
    # `metric_date` (le jour des données, = "since" de la partition) est requis
    # dans la clé : sans lui, deux jours différents de la même métrique
    # s'écrasent mutuellement lors d'un upsert côté target.
    primary_keys = ["ig_user_id", "metric_name", "breakdown_type", "metric_date"]

    # On indique au SDK quelle colonne utiliser comme signet
    replication_key = "extraction_date"
    # On précise que les données ne sont pas triées chronologiquement
    is_sorted = False
    # Un seul bookmark par stream (et non un par partition since/until), pour que
    # self.get_context_state(None) dans `partitions` ci-dessous retrouve un
    # bookmark global plutôt qu'un par partition.
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
        # "active" (défaut legacy) = découpage jour par jour ; "inactive" = un
        # seul appel couvrant toute la plage since/until.
        day_by_day = self.get_param("generate_dates_range", "active") != "inactive"

        # 1. LECTURE ROBUSTE DE LA DATE (Contournement du SDK)
        # On ne peut pas utiliser get_starting_replication_key_value() ici : cette
        # méthode lit "starting_replication_value", un champ que le SDK n'écrit
        # qu'après avoir évalué `partitions` (donc toujours vide à ce stade). On lit
        # directement le bookmark persisté du run précédent : "replication_key_value".
        state_bookmark = self.get_context_state(None).get("replication_key_value")
        
        if state_bookmark:
            # On reprend depuis le dernier signet (ex: "2026-06-18T18:39...")
            # On garde juste les 10 premiers caractères (YYYY-MM-DD)
            last_date_executes = date.fromisoformat(state_bookmark[:10])
            self.logger.info(f"Reprise depuis le signet (State) : {last_date_executes}")
        else:
            # Première exécution : on lit la config, sinon on calcule un défaut.
            start_date_str = self.get_param("start_date")
            if start_date_str:
                last_date_executes = date.fromisoformat(start_date_str[:10])
                self.logger.info(f"Première exécution, démarrage forcé à : {last_date_executes}")
            else:
                # Pas de 'start_date' fournie : on retombe sur le 1er jour du mois
                # en cours, moins 12 mois (ex: exécution le 19/06/2026 -> 01/06/2025).
                last_date_executes = today.replace(day=1) - relativedelta(months=12)
                self.logger.info(
                    "Première exécution, aucune 'start_date' fournie : valeur par "
                    f"défaut calculée (1er du mois - 12 mois) = {last_date_executes}"
                )

        # On retient le bookmark tel qu'il était AU DÉBUT de cette run. La
        # consolidation (étape 2 ci-dessous) génère des partitions avec un "until"
        # antérieur à ce bookmark ; sans ce plancher, le SDK prendrait le max des
        # "extraction_date" vus dans CETTE run uniquement (cf. parse_response) et
        # ferait régresser le bookmark si le bloc "récent" (étape 3) est vide.
        self._run_start_bookmark = datetime(
            last_date_executes.year, last_date_executes.month, last_date_executes.day,
            tzinfo=timezone.utc,
        )

        if last_date_executes >= today:
            self.logger.info("Le script a déjà été exécuté aujourd'hui. Fin.")
            return []

        # 2. Règle métier : Consolidation du 1er du mois
        if last_date_executes.day == 1:
            self.logger.info("Début du mois : on consolide l'avant-dernier mois.")
            first_day_in_2_last_month = (last_date_executes - relativedelta(months=2)).replace(day=1)
            last_day_in_2_last_month = first_day_in_2_last_month + relativedelta(months=1) - timedelta(days=1)

            partitions.extend(self._build_range_partitions(
                first_day_in_2_last_month, last_day_in_2_last_month, day_by_day,
            ))

        # 3. Extraction de base (Données récentes)
        start_recent = last_date_executes - timedelta(days=days_to_subtract)
        end_recent = today - timedelta(days=1)

        partitions.extend(self._build_range_partitions(start_recent, end_recent, day_by_day))

        return partitions

    # 1. LE SCHÉMA HYBRIDE (Métadonnées + Data brute en JSONB)
    schema = th.PropertiesList(
        th.Property("ig_user_id", th.StringType, required=True),
        th.Property("metric_name", th.StringType),
        th.Property("breakdown_type", th.StringType),
        # Le jour métier des données extraites (= "since" de la partition)
        th.Property("metric_date", th.DateType, required=True),
        #  On ajoute la colonne au schéma de la base de données
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
        # On passe le nom généré dynamiquement à la classe parente
        super().__init__(tap=tap, name=name, **kwargs)

        self.metric_name = metric_name
        self.breakdown = breakdown
        self._override_start_date = start_date
        self._override_days_to_subtract = days_to_subtract
        self._override_period = period
        self._override_timeframe = timeframe
        self._override_metric_type = metric_type
        self._override_generate_dates_range = generate_dates_range

        # On définit le chemin d'URL dynamiquement avec l'ID du client
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
        """
        ZÉRO TRANSFORMATION MÉTIER.
        On emballe simplement la réponse de Meta avec les métadonnées.
        """
        # On utilise le "until" de la partition courante (posé par get_url_params
        # dans client.py) comme valeur de bookmark : il représente le jour suivant
        # la dernière journée de données réellement couverte, pas l'heure d'exécution.
        # On la plafonne par le bookmark de début de run pour que les partitions de
        # consolidation (dates passées) ne fassent jamais reculer le signet.
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