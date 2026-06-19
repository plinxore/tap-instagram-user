"""InstagramUser tap class."""

import sys
from typing import List

from singer_sdk import Tap, Stream
from singer_sdk import typing as th

# On prépare l'import de notre flux générique (qui sera codé à la prochaine étape)
from tap_instagram_user.streams import MetaRawInsightsStream

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class TapInstagramUser(Tap):
    """Extracteur personnalisé pour l'API Meta (Instagram Insights)."""
    
    name = "tap-instagram-user"
    # Nom du package PyPI réellement installé (différent de `name` ci-dessus),
    # nécessaire pour que get_plugin_version() résolve la bonne version.
    package_name = "plinxore-tap-instagram-user"

    # 1. DÉFINITION DES PARAMÈTRES ATTENDUS
    # Supabase/Dagster devront injecter ces deux valeurs
    config_jsonschema = th.PropertiesList(
        th.Property(
            "access_token",
            th.StringType,
            required=True,
            secret=True, # Masque le token dans les logs
            description="Le Long-Lived Token du client"
        ),
        th.Property(
            "ig_user_id",
            th.StringType,
            required=True,
            description="L'ID du compte Instagram professionnel"
        ),
        # La date de départ en cas de première extraction
        th.Property(
            "start_date",
            th.DateTimeType,
            description=(
                "Valeur par défaut de 'start_date' pour toutes les métriques en cas "
                "de première extraction (ignorée dès qu'un bookmark existe). "
                "Surchageable par entrée dans `metrics` (ex: 2026-05-01T00:00:00Z). "
                "Si absente, valeur par défaut calculée automatiquement : le 1er du "
                "mois en cours moins 12 mois."
            ),
        ),
        th.Property(
            "days_to_subtract",
            th.IntegerType,
            default=0,
            description=(
                "Valeur par défaut du nombre de jours déjà couverts à ré-extraire à "
                "chaque run, en plus des jours réellement nouveaux (fenêtre de "
                "chevauchement, utile car les insights Meta peuvent encore se "
                "corriger plusieurs jours après leur première extraction). "
                "0 = pas de ré-extraction. Surchageable par entrée dans `metrics`."
            ),
        ),
        th.Property(
            "period",
            th.StringType,
            default="day",
            description=(
                "Valeur par défaut de la granularité demandée à l'API Meta Insights "
                "(paramètre `period`). Surchageable par entrée dans `metrics`."
            ),
        ),
        th.Property(
            "timeframe",
            th.StringType,
            description=(
                "Valeur par défaut du paramètre `timeframe` optionnel transmis à "
                "l'API Meta Insights. Surchageable par entrée dans `metrics`."
            ),
        ),
        th.Property(
            "metric_type",
            th.StringType,
            default="total_value",
            description=(
                "Valeur par défaut du paramètre `metric_type` transmis à l'API Meta "
                "Insights pour chaque métrique. Surchageable par entrée dans `metrics`."
            ),
        ),
        th.Property(
            "generate_dates_range",
            th.StringType,
            default="active",
            allowed_values=["active", "inactive"],
            description=(
                "'active' (défaut) : un appel API par jour (since/until = 1 jour). "
                "'inactive' : un seul appel couvrant toute la plage since/until "
                "(moins d'appels API, mais perd la granularité jour par jour selon "
                "ce que renvoie l'API pour la métrique). Surchageable par entrée "
                "dans `metrics`."
            ),
        ),
        th.Property(
            "metrics",
            th.ArrayType(
                th.ObjectType(
                    th.Property(
                        "metric",
                        th.StringType,
                        required=True,
                        description="Nom de la métrique Meta Insights (ex: views, reach, impressions).",
                    ),
                    th.Property(
                        "breakdowns",
                        th.ArrayType(th.StringType),
                        description=(
                            "Breakdowns à extraire pour cette métrique. Une chaîne "
                            "vide génère un stream sans breakdown."
                        ),
                    ),
                    th.Property(
                        "start_date",
                        th.DateTimeType,
                        description="Surcharge 'start_date' pour cette métrique uniquement.",
                    ),
                    th.Property(
                        "days_to_subtract",
                        th.IntegerType,
                        description="Surcharge 'days_to_subtract' pour cette métrique uniquement.",
                    ),
                    th.Property(
                        "period",
                        th.StringType,
                        description="Surcharge 'period' pour cette métrique uniquement.",
                    ),
                    th.Property(
                        "timeframe",
                        th.StringType,
                        description="Surcharge 'timeframe' pour cette métrique uniquement.",
                    ),
                    th.Property(
                        "metric_type",
                        th.StringType,
                        description="Surcharge 'metric_type' pour cette métrique uniquement.",
                    ),
                    th.Property(
                        "generate_dates_range",
                        th.StringType,
                        allowed_values=["active", "inactive"],
                        description="Surcharge 'generate_dates_range' pour cette métrique uniquement.",
                    ),
                )
            ),
            required=True,
            description=(
                "Liste des métriques (et de leurs breakdowns) à extraire, un stream "
                "étant généré par combinaison métrique/breakdown. Chaque entrée peut "
                "surcharger start_date/days_to_subtract/period/timeframe/metric_type/"
                "generate_dates_range pour elle-même ; sinon la valeur globale "
                "ci-dessus s'applique. "
                "Obligatoire : aucune valeur par défaut."
            ),
        ),
    ).to_dict()


    @override
    def discover_streams(self) -> List[Stream]:
        """Retourne la liste des flux (tables) à extraire."""
        
        streams: List[Stream] = []

        # 1. Les métriques/breakdowns à extraire viennent de la config. "metrics"
        # est obligatoire (cf. config_jsonschema) : la validation du tap échoue
        # avant même d'arriver ici si elle est absente.
        metrics_config = self.config["metrics"]

        # 2. La boucle de génération dynamique
        for entry in metrics_config:
            metric = entry["metric"]
            breakdowns = entry.get("breakdowns") or [""]
            for breakdown in breakdowns:
                
                # Création d'un nom de table SQL-friendly (sans virgule)
                if breakdown:
                    safe_breakdown = breakdown.replace(",", "_and_")
                    stream_name = f"ig_{metric}_by_{safe_breakdown}"
                else:
                    stream_name = f"ig_{metric}_base"
                    
                # On instancie notre flux générique, en propageant les éventuelles
                # surcharges définies sur cette entrée `metrics` (None si absentes,
                # auquel cas get_param() retombe sur la valeur globale du tap).
                stream = MetaRawInsightsStream(
                    tap=self,
                    name=stream_name,
                    metric_name=metric,
                    breakdown=breakdown,
                    start_date=entry.get("start_date"),
                    days_to_subtract=entry.get("days_to_subtract"),
                    period=entry.get("period"),
                    timeframe=entry.get("timeframe"),
                    metric_type=entry.get("metric_type"),
                    generate_dates_range=entry.get("generate_dates_range"),
                )
                
                streams.append(stream)
                
        return streams


if __name__ == "__main__":
    TapInstagramUser.cli()