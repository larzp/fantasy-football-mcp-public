# VS Code + GitHub Copilot Integration Guide

## 🎯 **Multiple Ways to Use Your Fantasy Football MCP with VS Code**

Your Fantasy Football MCP server can integrate with VS Code and GitHub Copilot in several powerful ways:

---

## 🚀 **Option 1: MCP Extension (Recommended)**

### **Installation**
1. **Install the MCP Extension**:
   - Open VS Code
   - Go to Extensions (`Ctrl+Shift+X`)
   - Search for "MCP" or "Model Context Protocol" 
   - Install the official MCP extension

2. **Open the Workspace**:
   ```bash
   # In your project directory
   code .vscode/workspace.code-workspace
   ```

3. **Automatic Configuration**:
   - Your MCP server is already configured in `.vscode/settings.json`
   - Environment variables will be loaded from your `.env` file
   - Automatic token management continues to work

### **Usage**
- **Access MCP Tools**: Use Command Palette (`Ctrl+Shift+P`) → "MCP: Run Tool"
- **Available Commands**:
  - `MCP: Get Leagues` - View your fantasy leagues
  - `MCP: Get Optimal Lineup` - Generate optimal lineups
  - `MCP: Analyze Matchup` - Get matchup predictions
  - `MCP: Check Token Status` - Monitor API tokens

---

## 🤖 **Option 2: GitHub Copilot Chat Integration**

### **Enhanced Copilot Context**
Your setup includes a `copilot-context.json` file that tells GitHub Copilot about your fantasy football capabilities.

### **Smart Copilot Prompts**
Ask GitHub Copilot Chat:

```
@workspace Generate my optimal fantasy lineup for this week
```

```
@workspace Who should I target on waivers based on my leagues?
```

```
@workspace Analyze this trade: [player A] for [player B]
```

```
@workspace What does Reddit sentiment say about [player name]?
```

### **Code Generation with Context**
Copilot will understand your fantasy football domain and can:
- Generate lineup optimization scripts
- Create player analysis code  
- Build trade evaluation logic
- Write data visualization code

---

## 🛠️ **Option 3: VS Code Tasks**

Pre-configured tasks are available via `Ctrl+Shift+P` → "Tasks: Run Task":

### **Available Tasks**
- **Start Fantasy Football MCP Server** - Launch the MCP server
- **Test Token Management** - Verify automatic token refresh
- **Quick Test MCP Server** - Run comprehensive tests  
- **Run VS Code Integration Test** - Test VS Code-specific features
- **Refresh Yahoo Tokens** - Manually refresh API tokens

---

## 📁 **File Structure for VS Code**

```
fantasy-football-mcp-public/
├── .vscode/
│   ├── settings.json           # VS Code + MCP configuration
│   ├── tasks.json              # Pre-built tasks
│   ├── workspace.code-workspace # Workspace settings
│   └── copilot-context.json    # GitHub Copilot context
├── vscode_integration.py       # VS Code helper functions
└── [rest of your project]
```

---

## 🔧 **Configuration Details**

### **MCP Server Settings** 
Your `.vscode/settings.json` includes:
```json
{
  "mcp.servers": {
    "fantasy-football": {
      "command": "uv",
      "args": ["run", "python", "run_server.py"],
      "cwd": "${workspaceFolder}",
      "env": {
        "YAHOO_CLIENT_ID": "${env:YAHOO_CLIENT_ID}",
        "YAHOO_CLIENT_SECRET": "${env:YAHOO_CLIENT_SECRET}",
        "YAHOO_ACCESS_TOKEN": "${env:YAHOO_ACCESS_TOKEN}",
        "YAHOO_REFRESH_TOKEN": "${env:YAHOO_REFRESH_TOKEN}"
      }
    }
  }
}
```

### **Python Integration**
- **Interpreter**: Configured to use `uv run python`
- **Analysis**: Enhanced with project-specific paths
- **Formatting**: Black formatter enabled
- **Linting**: Pylint enabled with auto-fix

### **GitHub Copilot Enhancement**
- **Context Aware**: Understands fantasy football domain
- **Smart Suggestions**: Tailored to your MCP tools
- **Code Generation**: Fantasy-football specific patterns

---

## 🎮 **Usage Examples**

### **1. Interactive Development**
```python
# In a Python file, start typing and Copilot will suggest:

# Get my fantasy leagues
leagues = await fantasy_service.discover_leagues()

# Generate optimal lineup  
lineup = await get_optimal_lineup("league_123", week=1)

# Analyze matchup
analysis = await analyze_matchup("league_123", week=1)
```

### **2. Task Automation**
Use VS Code tasks to:
- Start/stop the MCP server
- Run tests and verifications
- Refresh API tokens
- Generate reports

### **3. Chat Integration**
In GitHub Copilot Chat:
- **"@workspace What's my best lineup this week?"**
- **"@workspace Show me waiver wire targets"**  
- **"@workspace Help me analyze this trade"**

---

## 🔍 **Troubleshooting**

### **MCP Extension Not Working**
1. Check extension is installed and enabled
2. Verify `.vscode/settings.json` MCP configuration
3. Ensure `uv` is in your PATH
4. Check terminal output for errors

### **Copilot Not Understanding Context**
1. Verify `copilot-context.json` exists in `.vscode/`
2. Reload VS Code window (`Ctrl+Shift+P` → "Reload Window")
3. Try using `@workspace` prefix in Copilot Chat

### **Token Management Issues**
1. Run task: "Test Token Management"
2. Check `.env` file has all required variables
3. Manually refresh: "Refresh Yahoo Tokens" task

### **Python Environment Issues**
1. Ensure UV is installed: `uv --version`
2. Check Python interpreter setting in VS Code
3. Reload window after environment changes

---

## 🎉 **Benefits of VS Code Integration**

### **Development Workflow**
- **Integrated Testing**: Run all tests from VS Code
- **Code Intelligence**: Copilot understands your fantasy domain
- **Task Automation**: One-click server management
- **Debug Support**: Full debugging capabilities

### **Enhanced Copilot**
- **Domain Awareness**: Copilot knows fantasy football concepts
- **Smart Suggestions**: Context-aware code completion  
- **Natural Language**: Ask questions in plain English
- **Code Generation**: Automatic fantasy football code patterns

### **Professional Setup**
- **Workspace Management**: Organized project structure
- **Environment Handling**: Automatic UV/Python setup
- **Extension Recommendations**: All needed extensions suggested
- **Configuration Management**: Consistent settings across machines

---

## 🚀 **Getting Started**

### **Quick Start**
1. **Open workspace**: `code .vscode/workspace.code-workspace`
2. **Install recommended extensions** (VS Code will prompt)
3. **Run task**: "Start Fantasy Football MCP Server"
4. **Try Copilot**: "@workspace Get my fantasy leagues"

### **First Commands to Try**
```bash
# In VS Code terminal
Ctrl+Shift+P → "Tasks: Run Task" → "Quick Test MCP Server"
Ctrl+Shift+P → "Tasks: Run Task" → "Test Token Management"
```

```
# In GitHub Copilot Chat
@workspace What fantasy football tools are available?
@workspace Generate my optimal lineup
@workspace Show me my leagues
```

You now have a **full VS Code + GitHub Copilot integration** with your Fantasy Football MCP server! 🏈✨