"""
VS Code Extension Helper for Fantasy Football MCP

This module provides helper functions to integrate the Fantasy Football MCP server
with VS Code and GitHub Copilot through various methods.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_server import fantasy_service


class VSCodeFantasyFootballHelper:
    """Helper class for VS Code integration."""
    
    def __init__(self):
        """Initialize the VS Code helper."""
        self.service = fantasy_service
    
    async def get_leagues_for_copilot(self) -> str:
        """
        Get leagues in a format suitable for GitHub Copilot context.
        
        Returns:
            Formatted string with league information for Copilot
        """
        try:
            leagues = await self.service.discover_leagues()
            
            if not leagues:
                return "No active fantasy football leagues found."
            
            result = "Available Fantasy Football Leagues:\n"
            result += "=" * 50 + "\n"
            
            for league_id, info in leagues.items():
                result += f"League: {info.get('name', 'Unknown')}\n"
                result += f"  ID: {league_id}\n"
                result += f"  Season: {info.get('season', 'Unknown')}\n"
                result += f"  Teams: {info.get('num_teams', 'Unknown')}\n"
                result += f"  Scoring: {info.get('scoring_type', 'Unknown')}\n"
                result += f"  Week: {info.get('current_week', 'Unknown')}\n"
                result += f"  Active: {'Yes' if info.get('is_active') else 'No'}\n"
                result += "-" * 30 + "\n"
            
            return result
            
        except Exception as e:
            return f"Error retrieving leagues: {str(e)}"
    
    async def get_optimal_lineup_for_copilot(
        self, 
        league_id: str,
        week: Optional[int] = None
    ) -> str:
        """
        Get optimal lineup in Copilot-friendly format.
        
        Args:
            league_id: League identifier
            week: Week number (defaults to current week)
            
        Returns:
            Formatted lineup recommendations
        """
        try:
            # Use the MCP server's get_optimal_lineup function
            from src.mcp_server import get_optimal_lineup
            
            result = await get_optimal_lineup(
                league_id=league_id,
                week=week or 1,
                strategy="balanced"
            )
            
            if result.get("status") == "error":
                return f"Error: {result.get('error', 'Unknown error')}"
            
            lineup = result.get("optimal_lineup", {})
            
            output = f"Optimal Lineup for League {league_id}\n"
            output += "=" * 50 + "\n"
            
            if lineup.get("lineup"):
                for position, player in lineup["lineup"].items():
                    if isinstance(player, dict):
                        name = player.get("name", "Unknown")
                        team = player.get("team", "")
                        projected = player.get("projected_points", 0)
                        output += f"{position}: {name} ({team}) - {projected:.1f} pts\n"
                    else:
                        output += f"{position}: {player}\n"
            
            if lineup.get("bench"):
                output += "\nBench:\n"
                for player in lineup["bench"]:
                    if isinstance(player, dict):
                        name = player.get("name", "Unknown")
                        team = player.get("team", "")
                        projected = player.get("projected_points", 0)
                        output += f"  {name} ({team}) - {projected:.1f} pts\n"
            
            if lineup.get("total_projected"):
                output += f"\nTotal Projected Points: {lineup['total_projected']:.1f}\n"
            
            return output
            
        except Exception as e:
            return f"Error getting optimal lineup: {str(e)}"
    
    def format_for_copilot_chat(self, data: Dict[str, Any]) -> str:
        """
        Format any fantasy data for GitHub Copilot Chat.
        
        Args:
            data: Data dictionary to format
            
        Returns:
            Copilot-friendly formatted string
        """
        try:
            if isinstance(data, dict):
                result = "Fantasy Football Data:\n"
                result += "=" * 40 + "\n"
                
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        result += f"{key}:\n{json.dumps(value, indent=2)}\n\n"
                    else:
                        result += f"{key}: {value}\n"
                
                return result
            else:
                return str(data)
                
        except Exception as e:
            return f"Error formatting data: {str(e)}"


# Global instance
vscode_helper = VSCodeFantasyFootballHelper()


# Convenience functions for VS Code integration
async def get_leagues():
    """Get leagues for VS Code/Copilot."""
    return await vscode_helper.get_leagues_for_copilot()


async def get_lineup(league_id: str, week: int = None):
    """Get optimal lineup for VS Code/Copilot."""
    return await vscode_helper.get_optimal_lineup_for_copilot(league_id, week)


def create_copilot_context_file():
    """
    Create a context file that GitHub Copilot can use to understand
    your fantasy football setup.
    """
    context = {
        "project": "Fantasy Football MCP Server",
        "description": "AI-powered fantasy football analysis and optimization",
        "capabilities": [
            "League discovery and management",
            "Optimal lineup generation",
            "Matchup analysis and predictions", 
            "Waiver wire target identification",
            "Trade evaluation and recommendations",
            "Reddit sentiment analysis",
            "Advanced statistical modeling"
        ],
        "apis": {
            "yahoo_fantasy": "Integration with Yahoo Fantasy Sports API",
            "reddit": "Sentiment analysis from Reddit discussions"
        },
        "key_functions": {
            "get_leagues": "Retrieve all available fantasy leagues",
            "get_optimal_lineup": "Generate optimal lineup recommendations",
            "analyze_matchup": "Analyze weekly matchup predictions",
            "get_waiver_targets": "Find top waiver wire targets",
            "analyze_trade": "Evaluate trade proposals",
            "analyze_reddit_sentiment": "Analyze player sentiment from Reddit"
        },
        "usage_examples": [
            "Ask Copilot: 'Generate optimal lineup for my main league'",
            "Ask Copilot: 'Who should I target on waivers this week?'",
            "Ask Copilot: 'Analyze the trade: my player for their player'",
            "Ask Copilot: 'What does Reddit think about [player name]?'"
        ]
    }
    
    context_file = project_root / ".vscode" / "copilot-context.json"
    context_file.parent.mkdir(exist_ok=True)
    
    with open(context_file, 'w') as f:
        json.dump(context, f, indent=2)
    
    return str(context_file)


# Example usage for testing
if __name__ == "__main__":
    async def main():
        """Test VS Code integration."""
        print("Testing VS Code Fantasy Football Integration...")
        print("=" * 60)
        
        # Test league retrieval
        print("Fetching leagues...")
        leagues = await get_leagues()
        print(leagues)
        print()
        
        # Create Copilot context file
        print("Creating Copilot context file...")
        context_file = create_copilot_context_file()
        print(f"Context file created: {context_file}")
        print()
        
        print("VS Code integration ready!")
        print("=" * 60)
        print("Next steps:")
        print("1. Install the MCP extension in VS Code")
        print("2. Open the workspace: .vscode/workspace.code-workspace")
        print("3. Use GitHub Copilot with fantasy football context")
    
    asyncio.run(main())