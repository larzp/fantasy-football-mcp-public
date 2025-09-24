# MCP Server Configuration for Claude Desktop

To use this Fantasy Football MCP server with Claude Desktop:

## 1. Locate your Claude Desktop config file:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

## 2. Add this configuration to your claude_desktop_config.json:

```json
{
  "mcpServers": {
    "fantasy-football": {
      "command": "uv",
      "args": [
        "run", 
        "python", 
        "run_server.py"
      ],
      "cwd": "d:\\Code2025\\fantasy-football-mcp-public",
      "env": {
        "YAHOO_CLIENT_ID": "your_yahoo_client_id",
        "YAHOO_CLIENT_SECRET": "your_yahoo_client_secret",
        "YAHOO_ACCESS_TOKEN": "your_current_access_token",
        "YAHOO_REFRESH_TOKEN": "your_refresh_token"
      }
    }
  }
}
```

**Note**: The automatic token management system will update the `YAHOO_ACCESS_TOKEN` and `YAHOO_REFRESH_TOKEN` values automatically as they refresh.

## 3. Restart Claude Desktop

After adding the configuration, restart Claude Desktop completely.

## 4. Verify Connection

Once Claude Desktop restarts, you should see:
- A small plug icon (🔌) in the chat interface indicating MCP servers are connected
- The Fantasy Football MCP server should be available for use

## 5. Test the Tools

Try asking Claude to:
- "Get my fantasy leagues"
- "Get optimal lineup for week 1" 
- "Analyze my matchup"

## Troubleshooting

If the server doesn't connect:
1. Check that the `cwd` path is correct for your system
2. Ensure `uv` is in your PATH
3. Check Claude Desktop's developer tools for error messages
4. Verify the server runs manually with: `uv run python run_server.py`
5. Ensure your Yahoo API credentials are valid in the env section

## Available Tools

Your server provides these tools:
- `get_leagues` - Get available fantasy leagues
- `get_optimal_lineup` - Get optimal lineup recommendations  
- `analyze_matchup` - Analyze weekly matchups
- `get_waiver_targets` - Find waiver wire targets
- `analyze_trade` - Evaluate trade proposals
- `analyze_reddit_sentiment` - Analyze Reddit sentiment for players