#!/usr/bin/env python
"""Validate the documented Instagram fields/metrics against the LIVE Meta API.

Meta does not expose introspection on Instagram nodes (`?metadata=1` returns
only the id), so we instead test every candidate from `api_candidates.yaml`
one by one and record what the live API actually accepts. Output:

  docs/meta_api_reference.yaml   machine-readable status per item
  docs/meta_api_reference.md     human-readable tables (for the community)

Re-run periodically; the git diff of those two files is the changelog of
what Meta added or deprecated. Add newly documented items to
api_candidates.yaml when the docs introduce them.

Usage:
    python scripts/introspect.py [CONFIG_JSON]   # default: ./config.json
The config must contain `access_token` and `ig_user_id`.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE = "https://graph.facebook.com/v22.0"
ROOT = Path(__file__).resolve().parent.parent
MEDIA_TYPES = ["IMAGE", "VIDEO", "CAROUSEL_ALBUM"]


def _get(node_id: str, **params: str) -> tuple[int, str]:
    url = f"{BASE}/{node_id}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _classify(status: int, body: str) -> tuple[str, str]:
    """Return (status_label, note)."""
    if status == 200:
        return "ok", ""
    note = ""
    try:
        note = json.loads(body)["error"]["message"]
    except Exception:  # noqa: BLE001
        note = body[:120]
    if "nonexisting field" in body:
        return "deprecated", note
    if "does not support the" in body:
        return "unsupported", note
    return "error", note


def _check_field(token: str, node_id: str, field: str) -> dict:
    status, body = _get(node_id, fields=field, access_token=token)
    label, note = _classify(status, body)
    return {"name": field, "status": label, "note": note}


def _check_metric(token: str, node_id: str, metric: str, **extra: str) -> dict:
    status, body = _get(node_id, metric=metric, access_token=token, **extra)
    label, note = _classify(status, body)
    return {"name": metric, "status": label, "note": note}


def _authoritative_metrics(token: str, node_path: str) -> list[str]:
    """Discover the CURRENT valid metrics: a bogus metric makes the insights
    endpoint return "... must be one of the following values: a, b, c". This
    is Meta's authoritative live list (no doc dependency)."""
    _, body = _get(node_path, metric="__introspect_invalid__", access_token=token, period="day")
    try:
        msg = json.loads(body)["error"]["message"]
    except Exception:  # noqa: BLE001
        return []
    marker = "must be one of the following values:"
    if marker not in msg:
        return []
    return [m.strip() for m in msg.split(marker, 1)[1].split(",") if m.strip()]


def _sample_media_by_type(token: str, uid: str) -> dict[str, str]:
    """Find one post id per media_type by paginating /media."""
    found: dict[str, str] = {}
    url = f"{BASE}/{uid}/media?fields=id,media_type&limit=50&access_token={token}"
    for _ in range(20):  # cap pages
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        for post in data.get("data", []):
            mt = post.get("media_type")
            if mt in MEDIA_TYPES and mt not in found:
                found[mt] = post["id"]
        if len(found) == len(MEDIA_TYPES):
            break
        url = data.get("paging", {}).get("next")
        if not url:
            break
    return found


def introspect(config_path: Path) -> dict:
    cfg = json.loads(config_path.read_text())
    token, uid = cfg["access_token"], cfg["ig_user_id"]
    cand = yaml.safe_load((Path(__file__).parent / "api_candidates.yaml").read_text())

    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "api_version": "v22.0"}

    # ig_user fields
    out["ig_user"] = {
        "endpoint": cand["ig_user"]["endpoint"], "doc": cand["ig_user"]["doc"],
        "fields": [_check_field(token, uid, f) for f in cand["ig_user"]["candidates"]],
    }

    # ig_media fields (one sample post)
    sample = _sample_media_by_type(token, uid)
    any_media = next(iter(sample.values()))
    out["ig_media"] = {
        "endpoint": cand["ig_media"]["endpoint"], "doc": cand["ig_media"]["doc"],
        "fields": [_check_field(token, any_media, f) for f in cand["ig_media"]["candidates"]],
    }

    # ig_user_insights metrics (best effort: period=day, total_value) + the
    # authoritative live list discovered from the bogus-metric error.
    out["ig_user_insights"] = {
        "endpoint": cand["ig_user_insights"]["endpoint"], "doc": cand["ig_user_insights"]["doc"],
        "authoritative_live_metrics": _authoritative_metrics(token, f"{uid}/insights"),
        "metrics": [
            _check_metric(token, f"{uid}/insights", m, period="day", metric_type="total_value")
            for m in cand["ig_user_insights"]["candidates"]
        ],
    }

    # ig_media_insights metrics, per media_type -> validated compatibility
    by_type: dict[str, list[dict]] = {}
    for mt, mid in sample.items():
        by_type[mt] = [
            _check_metric(token, f"{mid}/insights", m)
            for m in cand["ig_media_insights"]["candidates"]
        ]
    out["ig_media_insights"] = {
        "endpoint": cand["ig_media_insights"]["endpoint"], "doc": cand["ig_media_insights"]["doc"],
        "authoritative_live_metrics": _authoritative_metrics(token, f"{any_media}/insights"),
        "by_media_type": by_type,
    }
    return out


def _icon(status: str) -> str:
    return {"ok": "✅", "deprecated": "❌", "unsupported": "—", "error": "⚠️"}.get(status, "?")


def to_markdown(ref: dict) -> str:
    lines = [
        "# Meta API reference (validated against the live API)",
        "",
        f"Generated: `{ref['generated_at']}` · API `{ref['api_version']}`.",
        "Regenerate with `python scripts/introspect.py`. ✅ valid · ❌ deprecated/gone · "
        "— not supported for this type · ⚠️ other error (see note).",
        "",
    ]
    for node in ("ig_user", "ig_media"):
        sec = ref[node]
        lines += [f"## `{node}` fields — `{sec['endpoint']}`", f"[doc]({sec['doc']})", "",
                  "| Field | Status | Note |", "|---|---|---|"]
        lines += [f"| `{f['name']}` | {_icon(f['status'])} | {f['note']} |" for f in sec["fields"]]
        lines.append("")
    sec = ref["ig_user_insights"]
    lines += [f"## `ig_user_insights` metrics — `{sec['endpoint']}`", f"[doc]({sec['doc']})", ""]
    if sec.get("authoritative_live_metrics"):
        lines += ["**Authoritative live metric list (from the API itself):** "
                  + ", ".join(f"`{m}`" for m in sec["authoritative_live_metrics"]), ""]
    lines += ["_Validation of our candidates (period=day, metric_type=total_value):_", "",
              "| Metric | Status | Note |", "|---|---|---|"]
    lines += [f"| `{m['name']}` | {_icon(m['status'])} | {m['note']} |" for m in sec["metrics"]]
    lines.append("")
    sec = ref["ig_media_insights"]
    lines += [f"## `ig_media_insights` metrics by media_type — `{sec['endpoint']}`", f"[doc]({sec['doc']})", ""]
    if sec.get("authoritative_live_metrics"):
        lines += ["**Authoritative live metric list (from the API itself):** "
                  + ", ".join(f"`{m}`" for m in sec["authoritative_live_metrics"]), ""]
    types = list(sec["by_media_type"].keys())
    lines += ["| Metric | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
    metrics = [m["name"] for m in next(iter(sec["by_media_type"].values()))]
    for i, name in enumerate(metrics):
        cells = " | ".join(_icon(sec["by_media_type"][t][i]["status"]) for t in types)
        lines.append(f"| `{name}` | {cells} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config.json"
    ref = introspect(config_path)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "meta_api_reference.yaml").write_text(yaml.safe_dump(ref, sort_keys=False, allow_unicode=True))
    (docs / "meta_api_reference.md").write_text(to_markdown(ref))
    print("Wrote docs/meta_api_reference.yaml and docs/meta_api_reference.md")


if __name__ == "__main__":
    main()
