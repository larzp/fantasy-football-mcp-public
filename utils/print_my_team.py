#!/usr/bin/env python3
"""
Print your Yahoo Fantasy team roster for the NFC Way North league.
This bypasses MCP and uses yfpy directly so we can validate auth + data end-to-end.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yfpy import YahooFantasySportsQuery


def load_env_file(path: Path = Path('.env')) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ[k] = v.strip("'\"")


def build_access_token_data() -> dict:
    return {
        'access_token': os.getenv('YAHOO_ACCESS_TOKEN', '').strip("'\""),
        'refresh_token': os.getenv('YAHOO_REFRESH_TOKEN', '').strip("'\""),
        'token_type': os.getenv('YAHOO_TOKEN_TYPE', 'bearer'),
        'token_time': float(os.getenv('YAHOO_TOKEN_TIME', '0') or 0),
        'guid': os.getenv('YAHOO_GUID', ''),
        'consumer_key': os.getenv('YAHOO_CONSUMER_KEY') or os.getenv('YAHOO_CLIENT_ID'),
        'consumer_secret': os.getenv('YAHOO_CONSUMER_SECRET') or os.getenv('YAHOO_CLIENT_SECRET'),
    }


def pick_user_team(teams, user_guid: Optional[str]) -> Optional[object]:
    # Try common attributes first
    for t in teams:
        # Exact flags some libs provide
        owned = getattr(t, 'is_owned_by_current_login', None)
        if owned is True:
            return t
    # Fallback by GUID in managers list
    if user_guid:
        for t in teams:
            managers = getattr(t, 'managers', None)
            if managers:
                # managers may be list of objects/dicts
                try:
                    for m in managers:
                        mg = getattr(m, 'guid', None) or (m.get('guid') if isinstance(m, dict) else None)
                        if mg and mg == user_guid:
                            return t
                except Exception:
                    pass
    # Last resort: return first team
    return teams[0] if teams else None


def fmt_name(val):
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode('utf-8', 'ignore')
        except Exception:
            return str(val)
    return val


def main():
    load_env_file()
    user_guid = os.getenv('YAHOO_GUID', '')
    token = build_access_token_data()

    if not token.get('consumer_key') or not token.get('access_token'):
        print('❌ Missing YAHOO_CONSUMER_KEY/CLIENT_ID or YAHOO_ACCESS_TOKEN in environment/.env')
        return

    print('🔑 Auth present, initializing Yahoo client...')
    client = YahooFantasySportsQuery(
        league_id='1',
        game_code='nfl',
        yahoo_access_token_json=token,
        browser_callback=False,
    )

    print('🏈 Fetching user leagues for current NFL game key...')
    leagues = client.get_user_leagues_by_game_key('nfl')
    league = None
    for lg in leagues or []:
        name = fmt_name(getattr(lg, 'name', ''))
        if name and 'NFC Way North' in name:
            league = lg
            break
    if not league:
        print('❌ Could not find league named "NFC Way North". Leagues seen:')
        for lg in leagues or []:
            print('  -', fmt_name(getattr(lg, 'name', 'Unknown')), getattr(lg, 'league_id', ''))
        return

    league_id = getattr(league, 'league_id', None)
    print(f'✅ League found: {fmt_name(getattr(league, "name", "?"))} (ID: {league_id})')

    # Switch client to league
    client.league_id = str(league_id)

    print('👥 Getting league teams...')
    teams = client.get_league_teams()
    if not teams:
        print('❌ No teams returned')
        return
    my_team = pick_user_team(teams, user_guid)
    if not my_team:
        print('❌ Could not identify your team. Listing teams:')
        for t in teams:
            print('  -', fmt_name(getattr(t, 'name', 'Unknown')), getattr(t, 'team_key', ''))
        return

    team_name = fmt_name(getattr(my_team, 'name', 'My Team'))
    team_key = getattr(my_team, 'team_key', None)
    print(f'✅ Your team: {team_name} (key: {team_key})')

    print('📋 Fetching roster (week 1 if available, else current)...')
    roster = None
    try:
        roster = client.get_team_roster_player_info_by_week(team_key, week=1)
    except Exception:
        try:
            roster = client.get_team_roster_player_info(team_key)
        except Exception as e:
            print('❌ Failed to fetch roster:', e)
            return

    players = []
    try:
        players = getattr(roster, 'players', roster) or []
    except Exception:
        pass

    if not players:
        print('ℹ️ No players found on roster')
        return

    print('\n🧾 Roster:')
    for p in players:
        # p may be a model or dict
        name = fmt_name(getattr(p, 'name', None) or (p.get('name') if isinstance(p, dict) else 'Unknown'))
        pos = getattr(p, 'position', None) or (p.get('position') if isinstance(p, dict) else None)
        status = getattr(p, 'status', None) or (p.get('status') if isinstance(p, dict) else None)
        print(f'  - {name} ({pos or "?"}) {"- " + status if status else ""}')


if __name__ == '__main__':
    main()
