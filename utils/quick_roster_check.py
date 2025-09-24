#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp_server import fantasy_service


async def main():
    leagues = await fantasy_service.discover_leagues()
    if not leagues:
        print(json.dumps({"status": "error", "error": "NO_LEAGUES"}))
        return
    # Pick first league
    lid = next(iter(leagues.keys()))
    roster = await fantasy_service.data_fetcher.get_user_team_roster(lid, week=1)
    print(json.dumps({
        "status": "success",
        "league_id": lid,
        "team_name": roster.get("team_name"),
        "player_count": len(roster.get("players", []))
    }, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
