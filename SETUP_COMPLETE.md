# Fantasy Football MCP - Environment Setup Guide

## 🎯 Quick Setup Summary

**You're almost ready!** Here's what you need to know:

### ✅ Required Environment Variables (You Have These!)
```bash
YAHOO_CLIENT_ID=your_yahoo_client_id           # ✅ Set
YAHOO_CLIENT_SECRET=your_yahoo_client_secret   # ✅ Set  
YAHOO_ACCESS_TOKEN=your_current_access_token   # ✅ Set
YAHOO_REFRESH_TOKEN=your_refresh_token         # ✅ Set
```

### 🔄 Automatic Token Management - **NO MANUAL WORK NEEDED!**

The system now includes **automatic token refresh** that:

- ✅ **Monitors your tokens** every 5 minutes
- ✅ **Refreshes automatically** 10 minutes before expiry  
- ✅ **Updates .env file** with new tokens
- ✅ **Updates Claude config** automatically
- ✅ **Works in background** - no interruption to your workflow

**You never need to manually refresh tokens again!**

---

## 🚀 Testing Your Setup

### 1. Test Automatic Token Management
```bash
python test_token_management.py
```

### 2. Test MCP Server
```bash
python run_server.py
```

### 3. Test in Claude Desktop
Your `claude_desktop_config.json` is already configured. Just:
1. Restart Claude Desktop
2. Ask: *"What fantasy football leagues do I have?"*

---

## 🔧 Optional Environment Variables

These are **optional** but already configured in your `.env`:

```bash
# Cache & Performance (already set)
CACHE_DIR=./.cache
CACHE_TTL_SECONDS=3600
YAHOO_API_RATE_LIMIT=100

# Logging (already set)
LOG_LEVEL=INFO
LOG_FILE=./logs/fantasy_football.log

# Advanced Features (already set)
ENABLE_ADVANCED_STATS=true
ENABLE_WEATHER_DATA=true
ENABLE_INJURY_REPORTS=true

# Reddit Sentiment Analysis (optional - set if you want Reddit features)
REDDIT_CLIENT_ID=your_reddit_client_id           # Currently placeholder
REDDIT_CLIENT_SECRET=your_reddit_client_secret   # Currently placeholder
REDDIT_USERNAME=your_reddit_username             # Currently placeholder
REDDIT_USER_AGENT=your_app_name:v1.0.0          # Currently placeholder
```

---

## 🔑 How Automatic Token Refresh Works

### Background Process
The MCP server automatically:
1. **Starts token manager** when server initializes
2. **Checks tokens** every 5 minutes
3. **Refreshes when needed** (10 minutes before expiry)
4. **Updates all config files** automatically

### Manual Control (If Needed)
You can also manually control tokens in Claude:

```
Check token status: "Check my Yahoo API token status"
Force refresh: "Refresh my Yahoo tokens"  
```

### Token Lifecycle
- **Yahoo tokens expire:** Every 1 hour
- **Automatic refresh:** 10 minutes before expiry
- **Refresh token:** Valid for ~1 year (renewed on each refresh)
- **Re-authentication needed:** Only if refresh token expires

---

## 🔍 Troubleshooting

### "Token expired" or "invalid_grant" errors
If automatic refresh fails, you may need to re-authenticate:
```bash
python utils/setup_yahoo_auth.py
```

### MCP Server won't start
1. Check you're in the right directory: `d:\Code2025\fantasy-football-mcp-public`
2. Verify Python version: `python --version` (should be 3.10+)
3. Check .env file exists with credentials

### Claude Desktop connection issues
1. Ensure `claude_desktop_config.json` is in the right location
2. Restart Claude Desktop completely
3. Check logs: `logs/fantasy_football.log`

---

## 📊 Status Commands

### Test Token Management
```bash
python test_token_management.py
```

### Check Server Status  
```bash
python -m src.mcp_server
```

### Verify Setup
```bash
python utils/verify_setup.py
```

---

## 🎉 You're All Set!

Your setup includes:

- ✅ **UV package manager** installed and configured
- ✅ **Python 3.10+** environment  
- ✅ **Yahoo API credentials** properly configured
- ✅ **Automatic token refresh** system active
- ✅ **MCP server** ready to run
- ✅ **Claude Desktop** integration configured

**Next steps:**
1. Run `python test_token_management.py` to verify everything works
2. Start using your Fantasy Football assistant in Claude Desktop!

No manual token management required - the system handles everything automatically! 🚀