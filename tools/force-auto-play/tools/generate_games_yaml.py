import argparse
import json
import re
import urllib.request
from pathlib import Path

import yaml

API_URLS = {
    "uat": "https://feg-uat.combosystems.co/api/fe/v3/game/list",
    "pp": "https://feg-pp.combosystems.co/api/fe/v3/game/list",
}

# JC list API often prefixes codes (e.g. SANA_FC_FC-SLOT-041 → FC-SLOT-041).
GAME_CODE_RE = re.compile(r"([A-Z]{2,}-[A-Z]+-\d+)", re.I)
CATEGORY_FROM_CODE = {
    "SLOT": "slot",
    "EGAME": "egame",
    "FISH": "fish",
    "FH": "fish",
    "LIVE": "live",
    "TABLE": "table",
}


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def normalize_game_id(raw_game_id: str) -> str:
    """Prefer sheet-style codes over platform-prefixed API ids."""
    raw = str(raw_game_id or "")
    match = GAME_CODE_RE.search(raw)
    return match.group(1).upper() if match else raw


def infer_category(game_id: str, api_category: str) -> str:
    """Prefer type embedded in game_id when API game_type buckets disagree."""
    match = re.match(r"[A-Z]+-([A-Z]+)-\d+", game_id, re.I)
    if match:
        mapped = CATEGORY_FROM_CODE.get(match.group(1).upper())
        if mapped:
            return mapped
    return api_category


def build_existing_lookup(existing_config: dict) -> tuple[dict, dict]:
    """Index existing games by game_id and normalized name for config preservation."""
    by_id: dict = {}
    by_name: dict = {}
    for _provider, games in (existing_config or {}).items():
        if not isinstance(games, dict):
            continue
        for game_id, game_data in games.items():
            if not isinstance(game_data, dict):
                continue
            by_id[str(game_id)] = game_data
            key = normalize_name(game_data.get("name", ""))
            if key:
                by_name[key] = game_data
    return by_id, by_name


def lookup_old_game_data(
    game_id: str,
    game_name: str,
    by_id: dict,
    by_name: dict,
) -> dict:
    old = by_id.get(str(game_id))
    if old:
        return old
    return by_name.get(normalize_name(game_name), {})


LANDSCAPE_SLOT_SPIN = {
    "prompt": "the large circular spin button with spiral arrow",
    "idle_prompt": "the large circular yellow/purple spin button",
    "region": {
        "x_start": 0.6,
        "x_end": 1.0,
        "y_start": 0.6,
        "y_end": 1.0,
    },
}

# FC slots are mobile-portrait in JC; landscape bottom-right defaults reintroduce X-drift.
FC_PORTRAIT_SLOT_SPIN = {
    "prompt": (
        "the largest circular main spin button at the exact bottom center, bigger "
        "than auto-play and turbo icons on its sides, round circle with spiral arrow, "
        "not auto-spin or turbo"
    ),
    "idle_prompt": (
        "the largest circular main spin button at the exact bottom center, bigger "
        "than auto-play and turbo icons on its sides, round circle with spiral arrow, "
        "not auto-spin or turbo"
    ),
    "region": {
        "x_start": 0.38,
        "x_end": 0.62,
        "y_start": 0.78,
        "y_end": 0.88,
    },
}


def _is_landscape_slot_spin(spin: dict | None) -> bool:
    if not isinstance(spin, dict):
        return False
    region = spin.get("region") or {}
    return (
        float(region.get("x_start", 0)) >= 0.55
        and float(region.get("x_end", 1)) >= 0.95
        and float(region.get("y_start", 0)) >= 0.55
    )


def resolve_slot_spin_button(provider: str | None, old_game_data: dict) -> dict:
    old_spin = old_game_data.get("spin_button")
    # JC mobile-portrait providers: bottom-center spin (not landscape bottom-right).
    if provider in ("FC", "JDB"):
        if old_spin and not _is_landscape_slot_spin(old_spin):
            return old_spin
        return dict(FC_PORTRAIT_SLOT_SPIN)
    if old_spin:
        return old_spin
    return dict(LANDSCAPE_SLOT_SPIN)


def build_game_data(
    category: str,
    game_name: str,
    old_game_data: dict,
    provider: str | None = None,
) -> dict:
    new_game_data = {
        "name": game_name,
        "category": category,
        "search_keyword": old_game_data.get("search_keyword", game_name),
    }

    if "skip_splash" in old_game_data:
        new_game_data["skip_splash"] = old_game_data["skip_splash"]

    if category == "slot":
        new_game_data["spin_button"] = resolve_slot_spin_button(provider, old_game_data)
        new_game_data["default_bet"] = old_game_data.get("default_bet", 1.0)
        new_game_data["balance_check"] = old_game_data.get(
            "balance_check",
            {"enabled": True, "keywords": ["balance", "total bet", "credit"]},
        )
    elif category == "fish":
        new_game_data["shoot_button"] = old_game_data.get(
            "shoot_button",
            {
                "prompt": "the cannon or weapon used to shoot",
                "idle_prompt": "the glowing cannon ready to fire",
                "region": {
                    "x_start": 0.0,
                    "x_end": 1.0,
                    "y_start": 0.5,
                    "y_end": 1.0,
                },
            },
        )
        new_game_data["default_bet"] = old_game_data.get("default_bet", 0.1)
        new_game_data["auto_shoot"] = old_game_data.get(
            "auto_shoot", {"enabled": True, "keywords": ["auto", "lock"]}
        )
    elif category in ("egame", "arcade"):
        new_game_data["action_button"] = old_game_data.get(
            "action_button",
            {
                "prompt": "the main action or drop button",
                "idle_prompt": "the main action button waiting for input",
                "region": {
                    "x_start": 0.2,
                    "x_end": 0.8,
                    "y_start": 0.5,
                    "y_end": 1.0,
                },
            },
        )
        new_game_data["default_bet"] = old_game_data.get("default_bet", 1.0)
        new_game_data["balance_check"] = old_game_data.get(
            "balance_check",
            {"enabled": True, "keywords": ["balance", "credit", "win"]},
        )
    elif category in ("live", "table"):
        new_game_data["bet_area"] = old_game_data.get(
            "bet_area",
            {
                "prompt": "the main betting area or chips",
                "region": {
                    "x_start": 0.0,
                    "x_end": 1.0,
                    "y_start": 0.5,
                    "y_end": 1.0,
                },
            },
        )
        new_game_data["default_bet"] = old_game_data.get("default_bet", 10.0)
    else:
        new_game_data["action_button"] = old_game_data.get(
            "action_button",
            {
                "prompt": "the main interact button",
                "region": {
                    "x_start": 0.0,
                    "x_end": 1.0,
                    "y_start": 0.0,
                    "y_end": 1.0,
                },
            },
        )

    return new_game_data


def fetch_game_list(env: str) -> dict:
    url = API_URLS[env]
    headers = {
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    req = urllib.request.Request(url, method="POST", data=b"{}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"API {env} returned status {response.status}")
        return json.loads(response.read().decode("utf-8"))


def generate_games_yaml(
    env: str = "uat",
    provider_filter: str | None = None,
    category_filter: str | None = None,
    yaml_path: Path | None = None,
) -> dict:
    yaml_path = yaml_path or Path("config/games.yaml")

    existing_config: dict = {}
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            existing_config = yaml.safe_load(f) or {}

    by_id, by_name = build_existing_lookup(existing_config)
    data = fetch_game_list(env)
    game_types = data.get("d", {}).get("game_type", {})

    if provider_filter:
        output_config = dict(existing_config)
        provider_games = dict(output_config.get(provider_filter, {}))
        if category_filter:
            provider_games = {
                gid: cfg
                for gid, cfg in provider_games.items()
                if not (isinstance(cfg, dict) and cfg.get("category") == category_filter)
            }
        else:
            provider_games = {}
        output_config[provider_filter] = provider_games
    else:
        output_config = {}

    updated_counts: dict[str, int] = {}

    for category, games in game_types.items():
        if category_filter and category != category_filter:
            continue
        if not isinstance(games, list):
            continue

        for game in games:
            provider = game.get("provider_id")
            raw_game_id = str(game.get("game_id") or "")
            game_id = normalize_game_id(raw_game_id)
            game_name = game.get("game_name", game_id)
            resolved_category = infer_category(game_id, category)

            if not provider:
                continue
            if provider_filter and provider != provider_filter:
                continue

            if provider not in output_config:
                output_config[provider] = {}

            old_game_data = lookup_old_game_data(game_id, game_name, by_id, by_name)
            if not old_game_data and raw_game_id != game_id:
                old_game_data = lookup_old_game_data(
                    raw_game_id, game_name, by_id, by_name
                )
            output_config[provider][game_id] = build_game_data(
                resolved_category, game_name, old_game_data, provider=provider
            )
            updated_counts[provider] = updated_counts.get(provider, 0) + 1

    class NoAliasDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            output_config,
            f,
            Dumper=NoAliasDumper,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )

    summary = {
        "env": env,
        "yaml_path": str(yaml_path),
        "categories": list(game_types.keys()),
        "updated_counts": updated_counts,
    }
    print(f"Successfully updated {yaml_path}")
    print(f"  env={env} provider_filter={provider_filter} category_filter={category_filter}")
    for provider, count in sorted(updated_counts.items()):
        print(f"  {provider}: {count} games")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Sync config/games.yaml from platform game list API")
    parser.add_argument("--env", choices=["uat", "pp"], default="uat", help="API environment (default: uat)")
    parser.add_argument("--provider", help="Only update this provider (merge mode, e.g. COMBO)")
    parser.add_argument("--category", help="Only include this category (e.g. slot)")
    parser.add_argument("--yaml", default="config/games.yaml", help="Output yaml path")
    args = parser.parse_args()

    generate_games_yaml(
        env=args.env,
        provider_filter=args.provider,
        category_filter=args.category,
        yaml_path=Path(args.yaml),
    )


if __name__ == "__main__":
    main()
