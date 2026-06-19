# tap-instagram-user

`tap-instagram-user` est un tap Singer pour l'API Meta Graph (Instagram Insights), construit avec le [Meltano Singer SDK](https://sdk.meltano.com).

Il extrait les métriques d'insights Instagram (`views`, `reach`, `impressions`, ...) jour par jour, avec une stratégie ELT : aucune transformation métier n'est appliquée côté tap, la réponse brute de l'API est stockée dans une colonne `raw_data` (JSON), aux côtés de métadonnées (`ig_user_id`, `metric_name`, `breakdown_type`, `metric_date`, `extraction_date`).

## Installation

```bash
uv sync
```

## Configuration

### Paramètres principaux

| Paramètre | Obligatoire | Description |
|---|---|---|
| `access_token` | oui | Long-Lived Token Meta du compte Instagram professionnel |
| `ig_user_id` | oui | ID du compte Instagram professionnel |
| `metrics` | oui | Liste des métriques (et de leurs breakdowns) à extraire — voir ci-dessous |
| `start_date` | non | Date de départ en cas de première extraction. Si absente, calculée automatiquement (1er du mois en cours moins 12 mois) |
| `days_to_subtract` | non (défaut `0`) | Fenêtre de chevauchement : nombre de jours déjà couverts à ré-extraire à chaque run (utile car les insights Meta peuvent encore se corriger après coup) |
| `period` | non (défaut `"day"`) | Granularité demandée à l'API Meta Insights |
| `timeframe` | non | Paramètre `timeframe` optionnel transmis à l'API |
| `metric_type` | non (défaut `"total_value"`) | Paramètre `metric_type` transmis à l'API |
| `generate_dates_range` | non (défaut `"active"`) | `"active"` = un appel API par jour ; `"inactive"` = un seul appel sur toute la plage |

### `metrics`

Chaque entrée définit une métrique et génère un stream par combinaison métrique/breakdown (ex: `views` + `follow_type` → stream `ig_views_by_follow_type`). Une entrée peut surcharger n'importe lequel des paramètres ci-dessus (sauf `access_token`/`ig_user_id`, toujours globaux) pour elle-même uniquement :

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

Voir [config.template.json](config.template.json) pour un exemple complet.

### Configuration via variables d'environnement

Copier `.env.example` vers `.env` et renseigner les vraies valeurs (jamais commité). Convention Meltano : `<PLUGIN_NAME>_<SETTING_NAME>` en majuscules, ex. `TAP_INSTAGRAM_USER_ACCESS_TOKEN`.

La liste complète des settings est disponible via :

```bash
tap-instagram-user --about
```

## Usage

### En CLI direct (sans Meltano)

```bash
tap-instagram-user --config config.json --discover > catalog.json
tap-instagram-user --config config.json --catalog catalog.json --state state.json
```

### Via Meltano (recommandé)

```bash
# Installer le CLI Meltano (si pas déjà fait)
pipx install meltano

# Installer les plugins déclarés dans meltano.yml
meltano install

# Vérifier la config
meltano config tap-instagram-user list
meltano config test tap-instagram-user

# Lancer le pipeline (extraction -> chargement Postgres)
meltano run tap-instagram-user target-postgres
```

Meltano gère automatiquement l'état (bookmarks) entre les runs via sa propre base système — pas besoin de manipuler de fichier `state.json` manuellement.

## Développement

### Tests

```bash
uv run pytest
```

### Détails d'implémentation notables

- **Bookmark** : basé sur le `until` de chaque partition jour, plafonné pour ne jamais régresser (notamment lors de la consolidation du 1er du mois). Un seul bookmark par stream (`state_partitioning_keys = []`), pas un par partition.
- **Primary key** : inclut `metric_date` (le jour des données) en plus de `ig_user_id`/`metric_name`/`breakdown_type`, pour éviter qu'un upsert côté target n'écrase les données d'un autre jour.
- **Consolidation mensuelle** : au 1er du mois, le tap ré-extrait automatiquement l'avant-dernier mois en entier (les insights Meta peuvent encore se corriger après publication).

Voir le code dans [tap_instagram_user/streams.py](tap_instagram_user/streams.py) et [tap_instagram_user/client.py](tap_instagram_user/client.py) pour le détail.

### SDK Dev Guide

Voir le [guide de développement du SDK](https://sdk.meltano.com/en/latest/dev_guide.html) pour plus d'informations sur le Meltano Singer SDK.
