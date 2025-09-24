"""
Yahoo Fantasy Sports API Data Fetcher Agent.

This module provides the DataFetcherAgent class that handles all Yahoo Fantasy Sports
API interactions including OAuth2 authentication, data fetching with rate limiting,
and intelligent caching through the cache manager.
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from loguru import logger
from yfpy import YahooFantasySportsQuery
from yfpy.models import Game, League, Matchup
from yfpy.models import Player as YfpyPlayer
from yfpy.models import Roster, Team

from config.settings import Settings

from ..models.lineup import Lineup
from ..models.matchup import GameStatus
from ..models.matchup import Matchup as FantasyMatchup
from ..models.player import (InjuryReport, InjuryStatus, Player, PlayerStats,
                             Position)
from ..models.player import Team as NFLTeam
from .cache_manager import CacheManagerAgent


class APIEndpoint(str, Enum):
    """Yahoo Fantasy Sports API endpoints."""
    USER_LEAGUES = "user_leagues"
    LEAGUE_INFO = "league_info"
    LEAGUE_TEAMS = "league_teams"
    TEAM_ROSTER = "team_roster"
    TEAM_MATCHUP = "team_matchup"
    PLAYER_INFO = "player_info"
    AVAILABLE_PLAYERS = "available_players"
    INJURY_REPORT = "injury_report"
    LEAGUE_STANDINGS = "league_standings"
    LEAGUE_TRANSACTIONS = "league_transactions"


class RateLimitError(Exception):
    """Exception raised when API rate limit is exceeded."""
    pass


class AuthenticationError(Exception):
    """Exception raised when authentication fails."""
    pass


@dataclass
class APIRequest:
    """API request wrapper with retry logic."""
    endpoint: APIEndpoint
    params: Dict[str, Any]
    attempt: int = 0
    max_retries: int = 3
    backoff_factor: float = 2.0
    timeout: int = 30


@dataclass
class RateLimitTracker:
    """Track API rate limiting."""
    requests_per_window: int = 100
    window_seconds: int = 3600
    requests_made: int = 0
    window_start: datetime = None
    
    def __post_init__(self):
        if self.window_start is None:
            self.window_start = datetime.utcnow()
    
    def can_make_request(self) -> bool:
        """Check if we can make another request within rate limits."""
        now = datetime.utcnow()
        
        # Reset window if expired
        if now - self.window_start > timedelta(seconds=self.window_seconds):
            self.requests_made = 0
            self.window_start = now
        
        return self.requests_made < self.requests_per_window
    
    def record_request(self) -> None:
        """Record a successful API request."""
        self.requests_made += 1
    
    def time_until_reset(self) -> timedelta:
        """Get time until rate limit window resets."""
        window_end = self.window_start + timedelta(seconds=self.window_seconds)
        remaining = window_end - datetime.utcnow()
        return remaining if remaining.total_seconds() > 0 else timedelta(0)


class DataFetcherAgent:
    """
    Agent responsible for fetching data from Yahoo Fantasy Sports API.
    
    This agent handles:
    - OAuth2 authentication with Yahoo
    - Rate-limited API requests with retry logic
    - Parallel data fetching for multiple leagues
    - Intelligent caching of API responses
    - Data transformation to internal models
    - Graceful error handling and recovery
    """
    
    def __init__(self, settings: Settings, cache_manager: CacheManagerAgent):
        """
        Initialize the data fetcher agent.
        
        Args:
            settings: Application settings containing API configuration
            cache_manager: Cache manager for intelligent caching
        """
        self.settings = settings
        self.cache_manager = cache_manager
        
        # Rate limiting
        self.rate_limiter = RateLimitTracker(
            requests_per_window=settings.yahoo_api_rate_limit,
            window_seconds=settings.yahoo_api_rate_window_seconds
        )
        
        # Yahoo API client (initialized on first use)
        self._yahoo_client: Optional[YahooFantasySportsQuery] = None
        self._auth_token: Optional[str] = None
        self._auth_expires: Optional[datetime] = None
        
        # Session for HTTP requests
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Semaphore for controlling concurrent requests
        self._semaphore = asyncio.Semaphore(settings.max_workers)
        
        logger.info("DataFetcherAgent initialized")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
    
    async def initialize(self) -> None:
        """Initialize the data fetcher."""
        try:
            # Create HTTP session
            timeout = aiohttp.ClientTimeout(total=self.settings.async_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
            
            # Initialize Yahoo API client
            await self._initialize_yahoo_client()
            
            logger.info("DataFetcherAgent initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize DataFetcherAgent: {e}")
            raise
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if self._session:
                await self._session.close()
                
            logger.info("DataFetcherAgent cleaned up")
            
        except Exception as e:
            logger.error(f"Error during DataFetcherAgent cleanup: {e}")
    
    async def get_user_leagues(self, game_key: str = None) -> List[Dict[str, Any]]:
        """
        Get all leagues for the authenticated user.
        
        Args:
            game_key: Optional specific game/season (e.g., "nfl.2024")
            
        Returns:
            List of league information dictionaries
        """
        cache_key = f"user_leagues:{game_key or 'all'}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached user leagues for game: {game_key}")
            return cached_data
        
        try:
            # Make API request
            request = APIRequest(
                endpoint=APIEndpoint.USER_LEAGUES,
                params={"game_key": game_key or "nfl"}  # Default to current NFL season
            )
            
            leagues_data = await self._make_api_request(request)
            
            # Transform to our format
            leagues = []
            if leagues_data:
                # leagues_data is a list of League objects directly
                for league in leagues_data:
                    league_info = {
                        'league_id': getattr(league, 'league_id', None),
                        'league_key': getattr(league, 'league_key', None),
                        'name': getattr(league, 'name', 'Unknown').decode() if isinstance(getattr(league, 'name', ''), bytes) else getattr(league, 'name', 'Unknown'),
                        'season': getattr(league, 'season', None),
                        'is_finished': getattr(league, 'is_finished', False),
                        'num_teams': getattr(league, 'num_teams', None),
                        'scoring_type': getattr(league, 'scoring_type', None),
                        'league_type': getattr(league, 'league_type', None),
                        'url': getattr(league, 'url', None),
                        'current_week': getattr(league, 'current_week', None)
                    }
                    leagues.append(league_info)
            
            # Cache the results
            await self.cache_manager.set(
                cache_key, 
                leagues, 
                ttl=timedelta(hours=4),  # Leagues don't change often
                tags=["user_leagues", "yahoo_api"]
            )
            
            logger.info(f"Retrieved {len(leagues)} leagues for user")
            return leagues
            
        except Exception as e:
            logger.error(f"Error getting user leagues: {e}")
            raise
    
    async def get_roster(self, league_key: str, team_key: str, week: int = None) -> Dict[str, Any]:
        """
        Get team roster for a specific league and week.
        
        Args:
            league_key: Yahoo league identifier
            team_key: Yahoo team identifier
            week: Optional week number (current week if not specified)
            
        Returns:
            Roster information dictionary
        """
        cache_key = f"roster:{league_key}:{team_key}:{week or 'current'}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached roster for team {team_key}, week {week}")
            return cached_data
        
        try:
            # Make API request
            request = APIRequest(
                endpoint=APIEndpoint.TEAM_ROSTER,
                params={
                    "league_key": league_key,
                    "team_key": team_key,
                    "week": week
                }
            )
            
            roster_data = await self._make_api_request(request)
            
            # Transform roster data
            roster_info = {
                'team_key': team_key,
                'league_key': league_key,
                'week': week,
                'players': [],
                'last_updated': datetime.utcnow().isoformat()
            }
            
            if roster_data:
                if hasattr(roster_data, 'players'):
                    iterable = roster_data.players
                elif isinstance(roster_data, list):
                    iterable = roster_data
                else:
                    iterable = []
                for player in iterable:
                    player_info = await self._transform_yahoo_player(player)
                    roster_info['players'].append(player_info)
            
            # Cache with shorter TTL since rosters change frequently
            await self.cache_manager.set(
                cache_key,
                roster_info,
                ttl=timedelta(hours=2),
                tags=["roster", "yahoo_api", f"league:{league_key}"]
            )
            
            logger.info(f"Retrieved roster for team {team_key}, {len(roster_info['players'])} players")
            return roster_info
            
        except Exception as e:
            logger.error(f"Error getting roster for team {team_key}: {e}")
            raise

    async def get_league_teams(self, league_key: str) -> List[Dict[str, Any]]:
        """
        Get all teams for a league.

        Args:
            league_key: Yahoo league identifier (can be a numeric ID like '205238' or full key)

        Returns:
            List of teams with basic info.
        """
        cache_key = f"league_teams:{league_key}"

        cached = await self.cache_manager.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached teams for league {league_key}")
            return cached

        try:
            request = APIRequest(
                endpoint=APIEndpoint.LEAGUE_TEAMS,
                params={"league_key": league_key}
            )
            teams_data = await self._make_api_request(request)

            teams: List[Dict[str, Any]] = []
            if teams_data:
                for t in teams_data:
                    try:
                        name_val = getattr(t, 'name', 'Unknown')
                        if isinstance(name_val, (bytes, bytearray)):
                            try:
                                name_val = name_val.decode('utf-8', 'ignore')
                            except Exception:
                                name_val = str(name_val)
                        managers_info = []
                        managers = getattr(t, 'managers', None)
                        if managers:
                            for m in managers:
                                try:
                                    managers_info.append({
                                        'guid': getattr(m, 'guid', None) or (m.get('guid') if isinstance(m, dict) else None),
                                        'manager_id': getattr(m, 'manager_id', None) or (m.get('manager_id') if isinstance(m, dict) else None),
                                        'nickname': getattr(m, 'nickname', None) or (m.get('nickname') if isinstance(m, dict) else None),
                                    })
                                except Exception:
                                    continue

                        teams.append({
                            'team_key': getattr(t, 'team_key', None),
                            'team_id': getattr(t, 'team_id', None) or (getattr(t, 'team_key', '').split('.')[-1] if getattr(t, 'team_key', None) else None),
                            'name': name_val,
                            'is_owned_by_current_login': getattr(t, 'is_owned_by_current_login', None),
                            'managers': managers_info,
                            'url': getattr(t, 'url', None),
                            'waiver_priority': getattr(t, 'waiver_priority', None),
                            'number_of_moves': getattr(t, 'number_of_moves', None),
                            'number_of_trades': getattr(t, 'number_of_trades', None),
                        })
                    except Exception as te:
                        logger.warning(f"Failed to transform team object: {te}")

            await self.cache_manager.set(
                cache_key,
                teams,
                ttl=timedelta(hours=1),
                tags=["league_teams", "yahoo_api", f"league:{league_key}"]
            )

            logger.info(f"Retrieved {len(teams)} teams for league {league_key}")
            return teams
        except Exception as e:
            logger.error(f"Error getting teams for league {league_key}: {e}")
            raise

    async def get_user_team_key(self, league_key: str) -> Optional[str]:
        """Identify the current user's team key in the given league."""
        try:
            teams = await self.get_league_teams(league_key)
            if not teams:
                return None

            import os
            user_guid = os.getenv('YAHOO_GUID', '')

            # Prefer explicit ownership flag if available
            for t in teams:
                if t.get('is_owned_by_current_login') is True:
                    return t.get('team_key')

            # Fallback: match by GUID in managers
            if user_guid:
                for t in teams:
                    for m in t.get('managers') or []:
                        if m.get('guid') and m['guid'] == user_guid:
                            return t.get('team_key')

            # Last resort: return first team key (not ideal but unblocks flows)
            return teams[0].get('team_key')
        except Exception as e:
            logger.error(f"Failed to determine user's team in league {league_key}: {e}")
            return None

    async def get_user_team_roster(self, league_key: str, week: int = None) -> Dict[str, Any]:
        """Get the current user's roster for the specified league and optional week."""
        team_key = await self.get_user_team_key(league_key)
        if not team_key:
            raise Exception("Could not determine user's team in this league")

        roster = await self.get_roster(league_key, team_key, week)

        # Enrich with team name
        try:
            teams = await self.get_league_teams(league_key)
            team = next((t for t in teams if t.get('team_key') == team_key), None)
            if team:
                roster['team_key'] = team_key
                roster['team_name'] = team.get('name')
        except Exception:
            pass

        return roster
    
    async def get_matchup(self, league_key: str, team_key: str, week: int) -> Dict[str, Any]:
        """
        Get matchup information for a team in a specific week.
        
        Args:
            league_key: Yahoo league identifier
            team_key: Yahoo team identifier
            week: Week number
            
        Returns:
            Matchup information dictionary
        """
        cache_key = f"matchup:{league_key}:{team_key}:{week}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached matchup for team {team_key}, week {week}")
            return cached_data
        
        try:
            # Make API request
            request = APIRequest(
                endpoint=APIEndpoint.TEAM_MATCHUP,
                params={
                    "league_key": league_key,
                    "team_key": team_key,
                    "week": week
                }
            )
            
            matchup_data = await self._make_api_request(request)
            
            # Transform matchup data
            matchup_info = {
                'league_key': league_key,
                'week': week,
                'teams': [],
                'is_playoffs': False,
                'is_consolation': False,
                'winner_team_key': None,
                'status': 'upcoming',
                'last_updated': datetime.utcnow().isoformat()
            }
            
            if matchup_data and hasattr(matchup_data, 'teams'):
                for team in matchup_data.teams:
                    team_info = {
                        'team_key': team.team_key,
                        'name': getattr(team, 'name', ''),
                        'projected_points': getattr(team, 'projected_points', None),
                        'actual_points': getattr(team, 'actual_points', None)
                    }
                    matchup_info['teams'].append(team_info)
            
            # Set matchup status and winner if available
            if hasattr(matchup_data, 'status'):
                matchup_info['status'] = matchup_data.status
            if hasattr(matchup_data, 'winner_team_key'):
                matchup_info['winner_team_key'] = matchup_data.winner_team_key
            
            # Cache matchup data
            await self.cache_manager.set(
                cache_key,
                matchup_info,
                ttl=timedelta(hours=1),  # Matchups update during games
                tags=["matchup", "yahoo_api", f"league:{league_key}", f"week:{week}"]
            )
            
            logger.info(f"Retrieved matchup for team {team_key}, week {week}")
            return matchup_info
            
        except Exception as e:
            logger.error(f"Error getting matchup for team {team_key}, week {week}: {e}")
            raise
    
    async def get_player(self, player_key: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information for a specific player.
        
        Args:
            player_key: Yahoo player identifier
            
        Returns:
            Player information dictionary or None if not found
        """
        cache_key = f"player:{player_key}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached player data for {player_key}")
            return cached_data
        
        try:
            # Make API request
            request = APIRequest(
                endpoint=APIEndpoint.PLAYER_INFO,
                params={"player_key": player_key}
            )
            
            player_data = await self._make_api_request(request)
            
            if not player_data:
                return None
            
            # Transform player data
            player_info = await self._transform_yahoo_player(player_data)
            
            # Cache player data with longer TTL (player info doesn't change much)
            await self.cache_manager.set(
                cache_key,
                player_info,
                ttl=timedelta(hours=6),
                tags=["player", "yahoo_api"]
            )
            
            logger.debug(f"Retrieved player data for {player_key}")
            return player_info
            
        except Exception as e:
            logger.error(f"Error getting player {player_key}: {e}")
            return None
    
    async def get_available_players(
        self,
        league_key: str,
        position: str = None,
        status: str = "A",  # A=Available, W=Waivers, T=Taken
        count: int = 25
    ) -> List[Dict[str, Any]]:
        """
        Get available players in a league.
        
        Args:
            league_key: Yahoo league identifier
            position: Optional position filter (QB, RB, WR, TE, K, DEF)
            status: Player status filter (A=Available, W=Waivers, T=Taken)
            count: Maximum number of players to return
            
        Returns:
            List of available player information dictionaries
        """
        cache_key = f"available_players:{league_key}:{position or 'all'}:{status}:{count}"
        
        # Check cache first (shorter TTL since availability changes frequently)
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached available players for league {league_key}")
            return cached_data
        
        try:
            # Make API request
            request = APIRequest(
                endpoint=APIEndpoint.AVAILABLE_PLAYERS,
                params={
                    "league_key": league_key,
                    "count": count,
                    "position": position,
                    "status": status
                }
            )
            
            players_data = await self._make_api_request(request)
            
            # Transform players data and filter to available
            available_players: List[Dict[str, Any]] = []
            requested_pos = position
            if players_data:
                if hasattr(players_data, 'players'):
                    iterable = players_data.players
                elif isinstance(players_data, list):
                    iterable = players_data
                else:
                    iterable = []
                for player in iterable:
                    player_info = await self._transform_yahoo_player(player)
                    # Filter by position if requested
                    if requested_pos and player_info.get('position') != requested_pos:
                        continue
                    # Filter by availability: include if not on a team
                    own = (player_info.get('ownership_status') or '').lower()
                    if own in ('freeagents', 'free agent', 'fa', 'available', ''):
                        # normalize projected points
                        try:
                            player_info['projected_points'] = float(player_info.get('projected_points') or 0)
                        except Exception:
                            player_info['projected_points'] = 0.0
                        available_players.append(player_info)
            
            # Cache with short TTL since player availability changes rapidly
            await self.cache_manager.set(
                cache_key,
                available_players,
                ttl=timedelta(minutes=30),
                tags=["available_players", "yahoo_api", f"league:{league_key}"]
            )
            
            logger.info(f"Retrieved {len(available_players)} available players for league {league_key}")
            return available_players
            
        except Exception as e:
            logger.error(f"Error getting available players for league {league_key}: {e}")
            raise
    
    async def get_injury_report(self, league_key: str = None) -> List[Dict[str, Any]]:
        """
        Get current injury report for players.
        
        Args:
            league_key: Optional league context for relevant players
            
        Returns:
            List of injury report dictionaries
        """
        cache_key = f"injury_report:{league_key or 'all'}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug("Returning cached injury report")
            return cached_data
        
        try:
            # This would typically call a specialized injury report endpoint
            # For now, we'll get it through available players with injury status
            available_players = await self.get_available_players(
                league_key, 
                status="A",  # All players to check injury status
                count=500
            )
            
            # Filter for injured players
            injured_players = []
            for player in available_players:
                if player.get('injury_status') and player['injury_status'] != 'Healthy':
                    injury_info = {
                        'player_key': player['player_key'],
                        'player_name': player['name'],
                        'team': player.get('team'),
                        'position': player.get('position'),
                        'injury_status': player['injury_status'],
                        'injury_note': player.get('injury_note', ''),
                        'last_updated': datetime.utcnow().isoformat()
                    }
                    injured_players.append(injury_info)
            
            # Cache injury report with medium TTL
            await self.cache_manager.set(
                cache_key,
                injured_players,
                ttl=timedelta(hours=2),
                tags=["injury_report", "yahoo_api"]
            )
            
            logger.info(f"Retrieved injury report with {len(injured_players)} injured players")
            return injured_players
            
        except Exception as e:
            logger.error(f"Error getting injury report: {e}")
            raise
    
    async def get_opponent_roster(
        self, 
        league_key: str, 
        opponent_team_key: str, 
        week: int = None
    ) -> Dict[str, Any]:
        """
        Get opponent team roster for matchup analysis.
        
        Args:
            league_key: Yahoo league identifier
            opponent_team_key: Yahoo opponent team identifier
            week: Optional week number (current week if not specified)
            
        Returns:
            Opponent roster information dictionary
        """
        cache_key = f"opponent_roster:{league_key}:{opponent_team_key}:{week or 'current'}"
        
        # Check cache first
        cached_data = await self.cache_manager.get(cache_key)
        if cached_data is not None:
            logger.debug(f"Returning cached opponent roster for team {opponent_team_key}, week {week}")
            return cached_data
        
        try:
            # Use the existing get_roster method with opponent team key
            roster_info = await self.get_roster(league_key, opponent_team_key, week)
            
            # Add opponent-specific metadata
            roster_info['is_opponent'] = True
            roster_info['opponent_team_key'] = opponent_team_key
            
            # Cache opponent roster data
            await self.cache_manager.set(
                cache_key,
                roster_info,
                ttl=timedelta(hours=2),  # Same TTL as regular rosters
                tags=["roster", "opponent", "yahoo_api", f"league:{league_key}"]
            )
            
            logger.info(f"Retrieved opponent roster for team {opponent_team_key}, {len(roster_info['players'])} players")
            return roster_info
            
        except Exception as e:
            logger.error(f"Error getting opponent roster for team {opponent_team_key}: {e}")
            raise
    
    async def fetch_multiple_leagues_data(
        self,
        league_keys: List[str],
        data_types: List[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch data for multiple leagues in parallel.
        
        Args:
            league_keys: List of Yahoo league identifiers
            data_types: List of data types to fetch (roster, matchup, standings, etc.)
            
        Returns:
            Dictionary mapping league_key to fetched data
        """
        if data_types is None:
            data_types = ["roster", "standings"]
        
        logger.info(f"Fetching data for {len(league_keys)} leagues in parallel")
        
        # Create tasks for parallel execution
        tasks = []
        for league_key in league_keys:
            task = asyncio.create_task(
                self._fetch_league_data(league_key, data_types),
                name=f"fetch_league_{league_key}"
            )
            tasks.append(task)
        
        # Execute tasks with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.settings.async_timeout_seconds * len(league_keys)
            )
            
            # Process results
            league_data = {}
            for i, result in enumerate(results):
                league_key = league_keys[i]
                if isinstance(result, Exception):
                    logger.error(f"Error fetching data for league {league_key}: {result}")
                    league_data[league_key] = {"error": str(result)}
                else:
                    league_data[league_key] = result
            
            logger.info(f"Completed parallel fetch for {len(league_keys)} leagues")
            return league_data
            
        except asyncio.TimeoutError:
            logger.error("Timeout while fetching multiple leagues data")
            raise
        except Exception as e:
            logger.error(f"Error in parallel league data fetch: {e}")
            raise
    
    async def _fetch_league_data(self, league_key: str, data_types: List[str]) -> Dict[str, Any]:
        """Fetch specific data types for a single league."""
        league_data = {"league_key": league_key}
        
        # Fetch each requested data type
        for data_type in data_types:
            try:
                if data_type == "roster":
                    # Get roster for the user's team (assuming first team)
                    # This would need team identification logic in a real implementation
                    pass
                elif data_type == "standings":
                    # Implementation for standings
                    pass
                elif data_type == "available_players":
                    league_data["available_players"] = await self.get_available_players(league_key)
                
            except Exception as e:
                logger.error(f"Error fetching {data_type} for league {league_key}: {e}")
                league_data[data_type] = {"error": str(e)}
        
        return league_data
    
    async def _initialize_yahoo_client(self) -> None:
        """Initialize Yahoo Fantasy Sports API client."""
        try:
            # Create Yahoo API client with OAuth2 credentials
            import os
            from pathlib import Path

            # Build access token dict manually from our environment variables
            # Include consumer key and secret in the token data as required by yfpy
            access_token_data = {
                "access_token": os.getenv("YAHOO_ACCESS_TOKEN", "").strip("'\""),
                "refresh_token": os.getenv("YAHOO_REFRESH_TOKEN", "").strip("'\""),
                "token_type": os.getenv("YAHOO_TOKEN_TYPE", "bearer"),
                "token_time": float(os.getenv("YAHOO_TOKEN_TIME", "0")),
                "guid": os.getenv("YAHOO_GUID", ""),
                "consumer_key": os.getenv("YAHOO_CONSUMER_KEY"),
                "consumer_secret": os.getenv("YAHOO_CONSUMER_SECRET")
            }
            
            # Initialize with minimal required parameters for user league queries
            self._yahoo_client = YahooFantasySportsQuery(
                league_id="1",  # Dummy value, will be updated per request
                game_code="nfl",
                game_id=None,  # Will be determined from current season
                yahoo_access_token_json=access_token_data,
                env_var_fallback=False,  # Don't fall back since we're passing tokens directly
                browser_callback=False  # Disable browser popup since we handle auth separately
            )
            
            logger.info("Yahoo API client initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Yahoo API client: {e}")
            raise AuthenticationError(f"Yahoo API authentication failed: {e}")
    
    async def _make_api_request(self, request: APIRequest) -> Any:
        """
        Make API request with rate limiting, retry logic, and error handling.
        
        Args:
            request: API request configuration
            
        Returns:
            API response data
        """
        async with self._semaphore:
            # Check rate limits
            if not self.rate_limiter.can_make_request():
                wait_time = self.rate_limiter.time_until_reset().total_seconds()
                logger.warning(f"Rate limit exceeded, waiting {wait_time} seconds")
                if wait_time > 0:
                    await asyncio.sleep(min(wait_time, 300))  # Max 5 minute wait
                
                if not self.rate_limiter.can_make_request():
                    raise RateLimitError("API rate limit exceeded")
            
            # Retry logic
            last_exception = None
            for attempt in range(request.max_retries + 1):
                try:
                    # Calculate backoff delay
                    if attempt > 0:
                        delay = request.backoff_factor ** attempt
                        logger.debug(f"Retrying request after {delay}s delay (attempt {attempt + 1})")
                        await asyncio.sleep(delay)
                    
                    # Make the actual API call
                    response = await self._execute_yahoo_request(request)
                    
                    # Record successful request
                    self.rate_limiter.record_request()
                    
                    logger.debug(f"API request successful: {request.endpoint}")
                    return response
                    
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_exception = e
                    logger.warning(f"API request failed (attempt {attempt + 1}): {e}")
                    
                    if attempt == request.max_retries:
                        break
                    
                except RateLimitError:
                    # Don't retry rate limit errors immediately
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error in API request: {e}")
                    raise
            
            # All retries exhausted
            logger.error(f"API request failed after {request.max_retries + 1} attempts")
            raise last_exception or Exception("API request failed")
    
    async def _execute_yahoo_request(self, request: APIRequest) -> Any:
        """Execute the actual Yahoo API request."""
        try:
            if not self._yahoo_client:
                await self._initialize_yahoo_client()
            
            # Route to appropriate Yahoo API method
            if request.endpoint == APIEndpoint.USER_LEAGUES:
                # Use the correct method name and pass game key for current NFL season
                game_key = request.params.get("game_key", "nfl")  # Default to current NFL season
                return self._yahoo_client.get_user_leagues_by_game_key(game_key)
            
            elif request.endpoint == APIEndpoint.LEAGUE_TEAMS:
                league_key = request.params["league_key"]
                # Set league context
                self._yahoo_client.league_id = league_key.split(".")[-1]
                return self._yahoo_client.get_league_teams()
            
            elif request.endpoint == APIEndpoint.TEAM_ROSTER:
                league_key = request.params["league_key"]
                team_key = request.params["team_key"]
                week = request.params.get("week")
                
                # Set league context
                self._yahoo_client.league_id = league_key.split(".")[-1]
                
                team_id = team_key.split(".")[-1]
                if week:
                    return self._yahoo_client.get_team_roster_player_stats_by_week(
                        team_id=team_id,
                        chosen_week=week
                    )
                else:
                    return self._yahoo_client.get_team_roster_player_stats(
                        team_id=team_id
                    )
            
            elif request.endpoint == APIEndpoint.TEAM_MATCHUP:
                league_key = request.params["league_key"]
                team_key = request.params["team_key"]
                week = request.params["week"]
                
                self._yahoo_client.league_id = league_key.split(".")[-1]
                return self._yahoo_client.get_team_matchups(
                    team_id=team_key.split(".")[-1],
                    chosen_week=week
                )
            
            elif request.endpoint == APIEndpoint.PLAYER_INFO:
                player_key = request.params["player_key"]
                return self._yahoo_client.get_player_info(player_key)
            
            elif request.endpoint == APIEndpoint.AVAILABLE_PLAYERS:
                league_key = request.params["league_key"]
                self._yahoo_client.league_id = league_key.split(".")[-1]
                count = request.params.get("count", 25)
                # Use generic league players; we'll filter client-side by ownership/position
                return self._yahoo_client.get_league_players(
                    player_count_limit=count,
                    player_count_start=0
                )
            
            else:
                raise ValueError(f"Unsupported endpoint: {request.endpoint}")
                
        except Exception as e:
            logger.error(f"Yahoo API request execution failed: {e}")
            raise
    
    async def _transform_yahoo_player(self, yahoo_player: YfpyPlayer) -> Dict[str, Any]:
        """
        Transform Yahoo player object to our internal format.
        
        Args:
            yahoo_player: Yahoo API player object
            
        Returns:
            Player information dictionary in our format
        """
        try:
            # Map Yahoo position to our Position enum
            position_map = {
                "QB": Position.QB,
                "RB": Position.RB,
                "WR": Position.WR,
                "TE": Position.TE,
                "K": Position.K,
                "DEF": Position.DEF
            }
            
            # Map Yahoo team to our Team enum
            yahoo_team = (
                getattr(yahoo_player, 'editorial_team_abbr', '')
                or getattr(yahoo_player, 'team_abbr', '')
                or getattr(getattr(yahoo_player, 'team', object()), 'abbr', '')
            )
            nfl_team = None
            try:
                nfl_team = NFLTeam(yahoo_team.upper()) if yahoo_team else None
            except ValueError:
                logger.warning(f"Unknown NFL team: {yahoo_team}")
            
            # Basic player information
            # Name resolution
            name_obj = getattr(yahoo_player, 'name', None)
            full_name = None
            if name_obj is not None:
                full_name = (
                    getattr(name_obj, 'full', None)
                    or (f"{getattr(name_obj, 'first', '')} {getattr(name_obj, 'last', '')}".strip())
                )
            if not full_name:
                full_name = getattr(yahoo_player, 'display_name', None) or 'Unknown Player'

            player_info = {
                'player_key': getattr(yahoo_player, 'player_key', ''),
                'name': full_name,
                'position': (
                    getattr(yahoo_player, 'display_position', '')
                    or getattr(yahoo_player, 'primary_position', '')
                    or getattr(yahoo_player, 'position', '')
                ),
                'team': yahoo_team,
                'jersey_number': getattr(yahoo_player, 'jersey_number', None),
                'bye_weeks': None,
                'is_undroppable': getattr(yahoo_player, 'is_undroppable', False),
                'ownership_status': None,
                'percent_owned': None
            }

            # Ownership model may be an object, not dict
            ownership = getattr(yahoo_player, 'ownership', None)
            if ownership is not None:
                try:
                    player_info['ownership_status'] = getattr(ownership, 'ownership_type', None) or (
                        ownership.get('ownership_type') if isinstance(ownership, dict) else None
                    )
                except Exception:
                    pass

            # Percent owned normalization
            po = getattr(yahoo_player, 'percent_owned', None)
            if po is not None:
                try:
                    player_info['percent_owned'] = (
                        float(po) if isinstance(po, (int, float, str)) and str(po).replace('.', '', 1).isdigit()
                        else float(getattr(po, 'value', None)) if hasattr(po, 'value') and isinstance(getattr(po, 'value'), (int, float, str)) and str(getattr(po, 'value')).replace('.', '', 1).isdigit()
                        else None
                    )
                except Exception:
                    player_info['percent_owned'] = None
            
            # Normalize bye weeks if present
            if hasattr(yahoo_player, 'bye_weeks') and yahoo_player.bye_weeks:
                try:
                    bw = yahoo_player.bye_weeks
                    if isinstance(bw, (list, tuple)):
                        player_info['bye_weeks'] = list(bw)
                    else:
                        # Attempt to read common attributes
                        player_info['bye_weeks'] = list(getattr(bw, 'weeks', [])) or [
                            getattr(bw, 'week', None)
                        ]
                except Exception:
                    player_info['bye_weeks'] = []
            else:
                player_info['bye_weeks'] = []

            # Injury information
            if hasattr(yahoo_player, 'status') and yahoo_player.status:
                player_info['injury_status'] = yahoo_player.status
            else:
                player_info['injury_status'] = 'Healthy'
            
            if hasattr(yahoo_player, 'injury_note'):
                try:
                    note = getattr(yahoo_player, 'injury_note')
                    player_info['injury_note'] = str(note) if note is not None else None
                except Exception:
                    pass
            
            # Statistics if available
            if hasattr(yahoo_player, 'player_stats') and yahoo_player.player_stats:
                stats = {}
                try:
                    for s in getattr(yahoo_player.player_stats, 'stats', []) or []:
                        try:
                            stat_meta = getattr(s, 'stat', None)
                            name = None
                            if stat_meta is not None:
                                name = getattr(stat_meta, 'display_name', None) or getattr(stat_meta, 'name', None)
                            if not name:
                                name = f"stat_{getattr(s, 'stat_id', getattr(stat_meta, 'stat_id', 'unknown'))}"
                            value = getattr(s, 'value', None)
                            stats[name] = value
                        except Exception:
                            continue
                except Exception:
                    pass
                if stats:
                    player_info['stats'] = stats
            
            # Projected points if available
            if hasattr(yahoo_player, 'player_points') and yahoo_player.player_points:
                player_info['projected_points'] = yahoo_player.player_points.total
            
            return player_info
            
        except Exception as e:
            logger.error(f"Error transforming Yahoo player data: {e}")
            # Return minimal player info if transformation fails
            return {
                'player_key': getattr(yahoo_player, 'player_key', ''),
                'name': 'Unknown Player',
                'position': '',
                'team': '',
                'error': str(e)
            }
    
    def _generate_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate consistent cache key from endpoint and parameters."""
        # Sort parameters for consistent key generation
        sorted_params = sorted(params.items())
        param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        # Create hash of the full request
        full_string = f"{endpoint}?{param_string}"
        return hashlib.md5(full_string.encode()).hexdigest()