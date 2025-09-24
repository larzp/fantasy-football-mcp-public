#!/usr/bin/env python3
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_server import fantasy_service

STARTER_SLOTS = [
    ("QB", 1),
    ("RB", 2),
    ("WR", 2),
    ("TE", 1),
    ("FLEX", 1),  # RB/WR/TE
    ("K", 1),
    ("DEF", 1),
]

FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def pick_lineup(players: List[Dict]) -> Dict:
    # sanitize projection
    for p in players:
        try:
            p["projected_points"] = float(p.get("projected_points") or 0)
        except Exception:
            p["projected_points"] = 0.0

    remaining = players.copy()
    starters = []

    def take_best(pos: str, count: int):
        nonlocal remaining, starters
        pool = [p for p in remaining if (p.get("position") == pos)]
        pool.sort(key=lambda x: x.get("projected_points", 0.0), reverse=True)
        chosen = pool[:count]
        starters.extend(chosen)
        chosen_keys = {id(c) for c in chosen}
        remaining = [p for p in remaining if id(p) not in chosen_keys]

    # Fill fixed slots
    for pos, cnt in STARTER_SLOTS:
        if pos == "FLEX":
            continue
        take_best(pos, cnt)

    # Fill FLEX from remaining eligible
    flex_pool = [p for p in remaining if p.get("position") in FLEX_ELIGIBLE]
    flex_pool.sort(key=lambda x: x.get("projected_points", 0.0), reverse=True)
    if flex_pool:
        starters.append(flex_pool[0])
        remaining.remove(flex_pool[0])

    bench = remaining
    return {
        "starters": starters,
        "bench": bench,
    }


async def main():
    leagues = await fantasy_service.discover_leagues()
    if not leagues:
        print(json.dumps({"status": "error", "error": "No leagues discovered"}))
        return
    league_id = next((lid for lid, info in leagues.items() if info.get("is_active")), None) or next(iter(leagues.keys()))

    roster = await fantasy_service.data_fetcher.get_user_team_roster(league_id)
    my_players = roster.get("players", [])

    lineup = pick_lineup(my_players)

    # Fetch available players for each position
    available = []
    for pos in [None, "QB", "RB", "WR", "TE", "K", "DEF"]:
        try:
            vals = await fantasy_service.data_fetcher.get_available_players(league_id, position=pos if pos else None, status="A", count=50)
            available.extend(vals or [])
        except Exception:
            continue

    # Normalize projections
    for p in available:
        try:
            p["projected_points"] = float(p.get("projected_points") or 0)
        except Exception:
            p["projected_points"] = 0.0

    # Find waiver targets: best available vs. weakest starters by slot
    # Build starter floor map by position
    from collections import defaultdict
    starter_floor = defaultdict(list)
    for s in lineup["starters"]:
        starter_floor[s.get("position")].append(s.get("projected_points") or 0.0)
    for k in starter_floor:
        starter_floor[k].sort()

    def should_target(candidate):
        pos = candidate.get("position")
        proj = candidate.get("projected_points", 0.0)
        if pos in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            floor = starter_floor.get(pos, [])
            if not floor:
                return True
            weakest = floor[0]
            return proj > weakest + 1.0  # needs to beat by 1 point
        # Consider FLEX eligibility: compare to weakest among RB/WR/TE flex pool
        if pos in FLEX_ELIGIBLE:
            flex_floor = []
            for fp in FLEX_ELIGIBLE:
                flex_floor.extend(starter_floor.get(fp, []))
            if flex_floor:
                weakest = sorted(flex_floor)[0]
                return proj > weakest + 1.0
        return False

    candidates = [p for p in available if should_target(p)]
    # De-dup by player_key
    seen = set()
    unique = []
    for p in sorted(candidates, key=lambda x: x.get("projected_points", 0.0), reverse=True):
        key = p.get("player_key")
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    waiver_targets = unique[:10]

    out = {
        "status": "success",
        "league_id": league_id,
        "team_name": roster.get("team_name"),
        "suggested_starters": [
            {"name": p.get("name"), "position": p.get("position"), "team": p.get("team"), "projected_points": p.get("projected_points")}
            for p in lineup["starters"]
        ],
        "bench_count": len(lineup["bench"]),
        "waiver_targets": [
            {"name": p.get("name"), "position": p.get("position"), "team": p.get("team"), "projected_points": p.get("projected_points")}
            for p in waiver_targets
        ],
    }
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
