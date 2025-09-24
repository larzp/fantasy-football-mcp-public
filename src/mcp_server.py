#!/usr/bin/env python3
"""
Fantasy Football MCP Server
Production-grade MCP server for Yahoo Fantasy Sports integration with
sophisticated lineup optimization and parallel processing capabilities.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from loguru import logger
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .agents.auto_token_manager import AutoTokenManager, get_auto_token_manager
from .agents.cache_manager import CacheManagerAgent
from .agents.data_fetcher import DataFetcherAgent
from .agents.decision import DecisionAgent
from .agents.optimization import OptimizationAgent
from .agents.reddit_analyzer import RedditSentimentAgent
from .agents.statistical import StatisticalAnalysisAgent
from .models.lineup import Lineup, LineupRecommendation
from .models.matchup import Matchup, MatchupAnalysis
from .models.player import Player
from .utils.constants import POSITIONS, ROSTER_POSITIONS

sys.path.append('..')

# Try to import settings, fall back to minimal config if it fails
try:
    from config.settings import Settings
except Exception as e:
    logger.warning(f"Could not load full settings: {e}. Using minimal config.")
    from pathlib import Path

    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        """Minimal settings class for MCP server."""
        mcp_server_name: str = "fantasy-football"
        mcp_server_version: str = "1.0.0" 
        log_level: str = "INFO"
        log_file: Path = Path("./logs/fantasy_football.log")
        cache_dir: Path = Path("./.cache")
        
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = False
            extra = "ignore"  # Ignore extra fields

load_dotenv()

# Create the MCP server instance
mcp = FastMCP("Fantasy Football MCP Server")

# Initialize the fantasy football server instance
class FantasyFootballService:
    """Fantasy Football service for MCP integration."""
    
    def __init__(self):
        """Initialize the Fantasy Football service."""
        self.settings = Settings()
        self._setup_logging()
        
        # Initialize automatic token manager
        self.auto_token_manager = None
        
        # Initialize agents (with error handling)
        try:
            self.cache_manager = CacheManagerAgent(self.settings)
            self.data_fetcher = DataFetcherAgent(self.settings, self.cache_manager)
            self.statistical = StatisticalAnalysisAgent(max_workers=4)
            self.optimization = OptimizationAgent(max_workers=4)
            self.decision = DecisionAgent()
            self.reddit_sentiment = RedditSentimentAgent(self.settings)
        except Exception as e:
            logger.warning(f"Could not initialize all agents: {e}. Some features may be limited.")
            # Initialize with None for now
            self.cache_manager = None
            self.data_fetcher = None
            self.statistical = None
            self.optimization = None
            self.decision = None
            self.reddit_sentiment = None
        
        # Track available leagues (discovered dynamically)
        self.available_leagues: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Fantasy Football MCP Server v{self.settings.mcp_server_version} initialized")
    
    async def _ensure_token_manager(self):
        """Ensure the auto token manager is running."""
        if self.auto_token_manager is None:
            try:
                self.auto_token_manager = await get_auto_token_manager(self.settings)
                logger.info("Automatic token manager started")
            except Exception as e:
                logger.error(f"Failed to start automatic token manager: {e}")
                self.auto_token_manager = None
    
    def _setup_logging(self):
        """Configure logging for the server."""
        log_path = Path(self.settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            self.settings.log_file,
            rotation="10 MB",
            retention="7 days",
            level=self.settings.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"
        )
    
    async def discover_leagues(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover all available leagues for the authenticated user.
        Returns a dictionary of league_id -> league_info.
        """
        try:
            # Ensure token manager is running
            await self._ensure_token_manager()
            
            if not self.data_fetcher:
                # Return mock data if agents aren't initialized
                self.available_leagues = {
                    "mock_league_1": {
                        'name': 'Mock League 1',
                        'season': '2025',
                        'num_teams': 10,
                        'scoring_type': 'standard',
                        'current_week': 1,
                        'is_active': True
                    }
                }
                logger.info("Using mock league data (agents not initialized)")
                return self.available_leagues
                
            leagues = await self.data_fetcher.get_user_leagues()
            self.available_leagues = {
                league['league_id']: {
                    'name': league['name'],
                    'season': league['season'],
                    'num_teams': league['num_teams'],
                    'scoring_type': league['scoring_type'],
                    'current_week': league.get('current_week', 1),
                    'is_active': league.get('is_finished', False) == False
                }
                for league in leagues
            }
            logger.info(f"Discovered {len(self.available_leagues)} leagues")
            return self.available_leagues
        except Exception as e:
            logger.error(f"Failed to discover leagues: {e}")
            return {}

# Initialize the service
fantasy_service = FantasyFootballService()

@mcp.tool()
async def get_leagues() -> Dict[str, Any]:
    """
    Get all available fantasy leagues for the authenticated user.
    
    Returns:
        Dictionary containing all discovered leagues with their details.
    """
    leagues = await fantasy_service.discover_leagues()
    
    return {
        "status": "success",
        "leagues": leagues,
        "total_count": len(leagues),
        "active_leagues": [
            lid for lid, info in leagues.items() 
            if info.get('is_active', False)
        ]
    }

@mcp.tool()
async def get_optimal_lineup(
    league_id: Optional[str] = None,
    week: Optional[int] = None,
    strategy: str = "balanced"
) -> Dict[str, Any]:
    """
    Get the mathematically optimal lineup for a given week.
    
    Args:
        league_id: The league ID. If not provided, uses all available leagues.
        week: The week number. If not provided, uses current week.
        strategy: Lineup strategy - 'conservative', 'aggressive', or 'balanced'.
    
    Returns:
        Optimal lineup recommendations with detailed analysis.
    """
    try:
        # Handle multiple leagues if no specific league_id provided
        if not league_id:
            if not fantasy_service.available_leagues:
                await fantasy_service.discover_leagues()
            
            results = {}
            # Process all active leagues
            for lid, info in fantasy_service.available_leagues.items():
                if info.get('is_active', False):
                    try:
                        lineup = await _get_optimal_lineup_for_league(lid, week, strategy)
                        results[lid] = {
                            "league_name": info['name'],
                            "lineup": lineup
                        }
                    except Exception as e:
                        logger.error(f"Failed to get lineup for league {lid}: {e}")
                        results[lid] = {"error": str(e)}
            
            return {
                "status": "success",
                "lineups": results,
                "strategy": strategy,
                "week": week
            }
        else:
            # Single league processing
            lineup = await _get_optimal_lineup_for_league(league_id, week, strategy)
            return {
                "status": "success",
                "league_id": league_id,
                "lineup": lineup,
                "strategy": strategy,
                "week": week
            }
            
    except Exception as e:
        logger.error(f"Failed to get optimal lineup: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def _get_optimal_lineup_for_league(
    league_id: str,
    week: Optional[int],
    strategy: str
) -> Dict[str, Any]:
    """Get optimal lineup for a specific league."""
    # Fetch roster and matchup data
    roster_data = await fantasy_service.data_fetcher.get_roster(league_id)
    matchup_data = await fantasy_service.data_fetcher.get_matchup(league_id, week)
    
    # Get player stats and projections in parallel
    player_tasks = [
        fantasy_service.statistical.analyze_player(player, week)
        for player in roster_data['players']
    ]
    player_analyses = await asyncio.gather(*player_tasks)
    
    # Run optimization with selected strategy
    optimal_lineup = await fantasy_service.optimization.optimize_lineup(
        players=player_analyses,
        roster_positions=roster_data['roster_positions'],
        strategy=strategy,
        matchup_context=matchup_data
    )
    
    # Get decision synthesis
    recommendation = await fantasy_service.decision.synthesize_lineup_decision(
        optimal_lineup=optimal_lineup,
        player_analyses=player_analyses,
        strategy=strategy,
        matchup_data=matchup_data
    )
    
    return recommendation.dict()

@mcp.tool()
async def analyze_matchup(
    league_id: Optional[str] = None,
    week: Optional[int] = None
) -> Dict[str, Any]:
    """
    Perform deep analysis of weekly matchup with win probability.
    
    Args:
        league_id: The league ID. If not provided, analyzes all leagues.
        week: The week number. If not provided, uses current week.
    
    Returns:
        Comprehensive matchup analysis with win probability.
    """
    try:
        if not league_id:
            # Analyze all active leagues
            if not fantasy_service.available_leagues:
                await fantasy_service.discover_leagues()
            
            results = {}
            for lid, info in fantasy_service.available_leagues.items():
                if info.get('is_active', False):
                    try:
                        analysis = await _analyze_matchup_for_league(lid, week)
                        results[lid] = {
                            "league_name": info['name'],
                            "analysis": analysis
                        }
                    except Exception as e:
                        logger.error(f"Failed to analyze matchup for league {lid}: {e}")
                        results[lid] = {"error": str(e)}
            
            return {
                "status": "success",
                "matchups": results,
                "week": week
            }
        else:
            analysis = await _analyze_matchup_for_league(league_id, week)
            return {
                "status": "success",
                "league_id": league_id,
                "analysis": analysis,
                "week": week
            }
            
    except Exception as e:
        logger.error(f"Failed to analyze matchup: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def _analyze_matchup_for_league(
    league_id: str,
    week: Optional[int]
) -> Dict[str, Any]:
    """Analyze matchup for a specific league."""
    try:
        # Get user's roster first
        my_roster = await fantasy_service.data_fetcher.get_roster(league_id, week)
        
        if not my_roster:
            return {
                "status": "error",
                "error": "Could not retrieve user roster",
                "suggestion": "Make sure the league is active and you have access"
            }
        
        # Since we can't get opponent data without active matchups,
        # let's provide basic team analysis
        my_analysis = await fantasy_service.statistical.analyze_team(my_roster, week)
        
        # Return enhanced analysis with current limitations noted
        enhanced_analysis = {
            "status": "info",
            "message": "Matchup analysis limited due to no active matchups",
            "league_id": league_id,
            "week": week,
            "my_team_analysis": my_analysis,
            "user_roster_summary": {
                "team_name": my_roster.get('team_name', 'My Team'),
                "player_count": len(my_roster.get('players', [])),
                "roster": my_roster.get('players', [])
            },
            "note": "Full matchup analysis will be available once the NFL season begins and matchups are active. Currently analyzing week 1 of the 2025 season."
        }
        
        return enhanced_analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze matchup for league {league_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "suggestion": "Try again when matchups are active, or check league access"
        }

@mcp.tool()
async def get_waiver_targets(
    league_id: Optional[str] = None,
    position: Optional[str] = None,
    max_results: int = 10
) -> Dict[str, Any]:
    """
    Identify high-value waiver wire targets using trending data.
    
    Args:
        league_id: The league ID. If not provided, analyzes all leagues.
        position: Filter by position (QB, RB, WR, TE, etc.)
        max_results: Maximum number of recommendations per league.
    
    Returns:
        Top waiver wire pickup recommendations.
    """
    try:
        if not league_id:
            # Get waiver targets for all leagues
            if not fantasy_service.available_leagues:
                await fantasy_service.discover_leagues()
            
            results = {}
            for lid, info in fantasy_service.available_leagues.items():
                if info.get('is_active', False):
                    try:
                        targets = await _get_waiver_targets_for_league(lid, position, max_results)
                        results[lid] = {
                            "league_name": info['name'],
                            "targets": targets
                        }
                    except Exception as e:
                        logger.error(f"Failed to get waiver targets for league {lid}: {e}")
                        results[lid] = {"error": str(e)}
            
            return {
                "status": "success",
                "waiver_targets": results,
                "position_filter": position,
                "max_results": max_results
            }
        else:
            targets = await _get_waiver_targets_for_league(league_id, position, max_results)
            return {
                "status": "success",
                "league_id": league_id,
                "targets": targets,
                "position_filter": position
            }
            
    except Exception as e:
        logger.error(f"Failed to get waiver targets: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def _get_waiver_targets_for_league(
    league_id: str,
    position: Optional[str],
    max_results: int
) -> List[Dict[str, Any]]:
    """Get waiver targets for a specific league."""
    # Get available players
    available_players = await fantasy_service.data_fetcher.get_available_players(
        league_id,
        position=position
    )
    
    # Analyze players in parallel
    analysis_tasks = [
        fantasy_service.statistical.analyze_waiver_value(player)
        for player in available_players[:max_results * 3]  # Analyze more to filter
    ]
    
    analyses = await asyncio.gather(*analysis_tasks)
    
    # Score and rank by waiver value
    recommendations = await fantasy_service.optimization.rank_waiver_targets(
        analyses,
        max_results=max_results
    )
    
    return recommendations

@mcp.tool()
async def analyze_trade(
    league_id: str,
    give_players: List[str],
    receive_players: List[str]
) -> Dict[str, Any]:
    """
    Evaluate trade proposals using rest-of-season projections.
    
    Args:
        league_id: The league ID for the trade.
        give_players: List of player IDs to trade away.
        receive_players: List of player IDs to receive.
    
    Returns:
        Trade analysis with recommendation and value assessment.
    """
    try:
        # Fetch player data for both sides
        give_data = await asyncio.gather(*[
            fantasy_service.data_fetcher.get_player(league_id, pid)
            for pid in give_players
        ])
        
        receive_data = await asyncio.gather(*[
            fantasy_service.data_fetcher.get_player(league_id, pid)
            for pid in receive_players
        ])
        
        # Get ROS projections for all players
        give_projections = await asyncio.gather(*[
            fantasy_service.statistical.get_ros_projection(player)
            for player in give_data
        ])
        
        receive_projections = await asyncio.gather(*[
            fantasy_service.statistical.get_ros_projection(player)
            for player in receive_data
        ])
        
        # Analyze trade impact
        trade_analysis = await fantasy_service.decision.analyze_trade(
            give_players=give_projections,
            receive_players=receive_projections,
            roster_context=await fantasy_service.data_fetcher.get_roster(league_id)
        )
        
        return {
            "status": "success",
            "league_id": league_id,
            "analysis": trade_analysis.dict(),
            "recommendation": trade_analysis.recommendation,
            "value_differential": trade_analysis.value_differential
        }
        
    except Exception as e:
        logger.error(f"Failed to analyze trade: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

@mcp.tool()
async def analyze_reddit_sentiment(
    players: List[str],
    time_window_hours: int = 48
) -> Dict[str, Any]:
    """
    Analyze Reddit sentiment for player Start/Sit decisions.
    
    Args:
        players: List of player names to compare (e.g., ["Josh Allen", "Jared Goff"])
        time_window_hours: How far back to look for Reddit posts (default 48 hours)
    
    Returns:
        Reddit sentiment analysis with Start/Sit recommendations based on community consensus.
    """
    try:
        if not players:
            return {
                "status": "error",
                "error": "No players provided for analysis"
            }
        
        # Single player analysis
        if len(players) == 1:
            sentiment = await fantasy_service.reddit_sentiment.analyze_player_sentiment(
                players[0],
                time_window_hours
            )
            return {
                "status": "success",
                "analysis_type": "single_player",
                "player": players[0],
                "sentiment_data": sentiment,
                "recommendation": sentiment.get('consensus', 'UNKNOWN'),
                "confidence": sentiment.get('hype_score', 0) * 100
            }
        
        # Multi-player comparison (Start/Sit decision)
        comparison = await fantasy_service.reddit_sentiment.compare_players_sentiment(
            players,
            time_window_hours
        )
        
        return {
            "status": "success",
            "analysis_type": "comparison",
            "players": players,
            "comparison_data": comparison,
            "recommendation": comparison.get('recommendation'),
            "confidence": comparison.get('confidence', 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to analyze Reddit sentiment: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

@mcp.resource("cache://status")
async def get_cache_status() -> str:
    """Get the current cache status and statistics."""
    stats = await fantasy_service.cache_manager.get_stats()
    return json.dumps(stats, indent=2)

@mcp.tool()
async def check_token_status() -> Dict[str, Any]:
    """
    Check the current Yahoo API token status and automatic refresh system.
    
    Returns:
        Token status information including expiry time, refresh history, and recommendations.
    """
    try:
        # Ensure token manager is running
        await fantasy_service._ensure_token_manager()
        
        if fantasy_service.auto_token_manager:
            status = fantasy_service.auto_token_manager.get_status()
            
            # Add human-readable information
            if status.get("auth_status", {}).get("has_tokens"):
                auth_status = status["auth_status"]
                expires_in_seconds = auth_status.get("expires_in_seconds", 0)
                
                if expires_in_seconds > 0:
                    hours = expires_in_seconds // 3600
                    minutes = (expires_in_seconds % 3600) // 60
                    status["human_readable"] = {
                        "expires_in": f"{hours}h {minutes}m",
                        "status": "✅ Token valid and auto-refresh active",
                        "next_action": "Automatic - no manual action needed"
                    }
                else:
                    status["human_readable"] = {
                        "expires_in": "Expired",
                        "status": "⚠️ Token expired or expiring soon",
                        "next_action": "Automatic refresh will occur on next API call"
                    }
            else:
                status["human_readable"] = {
                    "status": "❌ No valid tokens found",
                    "next_action": "Manual authentication required - run: python utils/setup_yahoo_auth.py"
                }
                
            return {
                "status": "success",
                "token_manager_running": status["running"],
                "automatic_refresh_enabled": True,
                "details": status
            }
        else:
            return {
                "status": "error",
                "token_manager_running": False,
                "automatic_refresh_enabled": False,
                "error": "Auto token manager not available",
                "recommendation": "Check your Yahoo API credentials in .env file"
            }
            
    except Exception as e:
        logger.error(f"Failed to check token status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "recommendation": "Ensure Yahoo API credentials are properly configured in .env file"
        }

@mcp.tool()
async def refresh_yahoo_tokens() -> Dict[str, Any]:
    """
    Manually refresh Yahoo API tokens immediately.
    
    Returns:
        Result of the token refresh operation.
    """
    try:
        # Ensure token manager is running
        await fantasy_service._ensure_token_manager()
        
        if not fantasy_service.auto_token_manager:
            return {
                "status": "error",
                "error": "Auto token manager not available",
                "recommendation": "Check your Yahoo API credentials in .env file"
            }
        
        logger.info("Manual token refresh requested")
        success = await fantasy_service.auto_token_manager.force_refresh()
        
        if success:
            status = fantasy_service.auto_token_manager.get_status()
            auth_status = status.get("auth_status", {})
            
            return {
                "status": "success",
                "message": "✅ Tokens refreshed successfully",
                "expires_at": auth_status.get("expires_at"),
                "expires_in_seconds": auth_status.get("expires_in_seconds", 0),
                "refresh_count": status.get("refresh_count", 0)
            }
        else:
            status = fantasy_service.auto_token_manager.get_status()
            return {
                "status": "error",
                "message": "❌ Token refresh failed",
                "error": status.get("last_error", "Unknown error"),
                "recommendation": "Check logs for details. May need manual re-authentication."
            }
            
    except Exception as e:
        logger.error(f"Failed to refresh tokens manually: {e}")
        return {
            "status": "error",
            "error": str(e),
            "recommendation": "Check Yahoo API credentials and internet connection"
        }

if __name__ == "__main__":
    logger.info("Starting Fantasy Football MCP Server...")
    mcp.run()