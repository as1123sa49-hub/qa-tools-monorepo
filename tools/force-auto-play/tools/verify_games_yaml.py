"""Validate config/games.yaml against platform game list API."""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import yaml

API_URLS = {
    "uat": "https://feg-uat.combosystems.co/api/fe/v3/game/list",
    "pp": "https://feg-pp.combosystems.co/api/fe/v3/game/list",
}

SLOT_REQUIRED_FIELDS = ("name", "category", "search_keyword", "spin_button")


def fetch_api_games(env: str, provider: str, category: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    req = urllib.request.Request(
        API_URLS[env], method="POST", data=b"{}", headers=headers
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    result: dict[str, str] = {}
    for cat, games in data.get("d", {}).get("game_type", {}).items():
        if cat != category or not isinstance(games, list):
            continue
        for game in games:
            if game.get("provider_id") == provider:
                gid = str(game["game_id"])
                result[gid] = game.get("game_name", gid)
    return result


def load_yaml_games(yaml_path: Path, provider: str, category: str) -> dict[str, dict]:
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    provider_games = data.get(provider, {})
    return {
        gid: cfg
        for gid, cfg in provider_games.items()
        if isinstance(cfg, dict) and cfg.get("category") == category
    }


def validate_yaml_structure(games: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    for game_id, cfg in games.items():
        for field in SLOT_REQUIRED_FIELDS:
            if field not in cfg:
                errors.append(f"{game_id}: missing field '{field}'")
        spin = cfg.get("spin_button")
        if isinstance(spin, dict):
            for sub in ("prompt", "idle_prompt", "region"):
                if sub not in spin:
                    errors.append(f"{game_id}: spin_button missing '{sub}'")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify games.yaml against platform API")
    parser.add_argument("--env", choices=["uat", "pp"], default="uat")
    parser.add_argument("--provider", default="COMBO")
    parser.add_argument("--category", default="slot")
    parser.add_argument("--yaml", default="config/games.yaml")
    parser.add_argument("--skip-api", action="store_true", help="Only validate yaml structure")
    args = parser.parse_args()

    yaml_path = Path(args.yaml)
    if not yaml_path.exists():
        print(f"ERROR: {yaml_path} not found")
        return 1

    yaml_games = load_yaml_games(yaml_path, args.provider, args.category)
    print(f"=== {args.provider} {args.category} in {yaml_path} ===")
    print(f"  count: {len(yaml_games)}")

    struct_errors = validate_yaml_structure(yaml_games)
    if struct_errors:
        print(f"\nStructure errors ({len(struct_errors)}):")
        for err in struct_errors[:20]:
            print(f"  - {err}")
        if len(struct_errors) > 20:
            print(f"  ... and {len(struct_errors) - 20} more")
        return 1

    print("  structure: OK")

    if args.skip_api:
        print("\nAll checks passed (yaml only).")
        return 0

    api_games = fetch_api_games(args.env, args.provider, args.category)
    print(f"\n=== API ({args.env}) ===")
    print(f"  count: {len(api_games)}")

    missing_in_yaml = sorted(set(api_games) - set(yaml_games))
    extra_in_yaml = sorted(set(yaml_games) - set(api_games))
    name_mismatch = [
        gid
        for gid in set(api_games) & set(yaml_games)
        if yaml_games[gid].get("name") != api_games[gid]
    ]

    ok = True
    if missing_in_yaml:
        ok = False
        print(f"\nMissing in yaml ({len(missing_in_yaml)}):")
        for gid in missing_in_yaml:
            print(f"  - {gid} ({api_games[gid]})")

    if extra_in_yaml:
        ok = False
        print(f"\nExtra in yaml (not in API) ({len(extra_in_yaml)}):")
        for gid in extra_in_yaml:
            print(f"  - {gid} ({yaml_games[gid].get('name')})")

    if name_mismatch:
        ok = False
        print(f"\nName mismatch ({len(name_mismatch)}):")
        for gid in name_mismatch[:10]:
            print(f"  - {gid}: yaml='{yaml_games[gid].get('name')}' api='{api_games[gid]}'")

    if ok:
        print(f"\nAll checks passed. {len(yaml_games)} games match API.")
        return 0

    print("\nVerification FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
