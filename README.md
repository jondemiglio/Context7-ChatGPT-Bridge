# Context7 ChatGPT Bridge

## Why This Exists

ChatGPT needs access to current programming documentation but requires specific `search` and `fetch` tools. Context7 provides excellent up-to-date docs but uses different tools (`resolve-library-id` and `get-library-docs`). This bridge translates between them, giving ChatGPT access to Context7's documentation database.

## What It Does

A bridge that allows ChatGPT to access up-to-date programming documentation through the Context7 MCP server. Implements ChatGPT's required `search` and `fetch` tools while using Context7's documentation database internally.

## Requirements

- **Node.js** >= 18.0.0
- **Python** >= 3.8

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the bridge:**
   ```bash
   python context7_bridge.py
   ```
   
   The script automatically starts ngrok and displays the ChatGPT-ready URL.

3. **Add to ChatGPT:**
   Copy the displayed URL to ChatGPT's MCP connectors:
   ```
   https://abc123.ngrok-free.app/sse
   ```

## Available Tools

### `search`
Search for programming libraries and frameworks. Supports both library names (e.g., "React", "MongoDB") and direct Context7 library IDs (e.g., "/reactjs/react.dev").

### `fetch`
Fetch comprehensive documentation for specific libraries. Supports advanced parameters:

- **Basic:** `library_id`
- **Topic-focused:** `library_id|topic:hooks`
- **Custom tokens:** `library_id|tokens:15000`
- **Combined:** `library_id|topic:authentication|tokens:12000`

### Example Topics

- `hooks` - React hooks, useEffect, useState
- `routing` - Navigation, route setup
- `authentication` - Login, security, JWT
- `installation` - Setup, configuration
- `api` - API reference, methods
- `examples` - Code examples, tutorials

## How It Works

```
ChatGPT → ngrok → Bridge → Context7 MCP Server → Documentation Database
```

1. ChatGPT sends search/fetch requests to your bridge
2. Bridge translates these to Context7's resolve-library-id/get-library-docs calls
3. Context7 returns current documentation
4. Bridge formats responses for ChatGPT

## Configuration

**Command-line options:**
```bash
python context7_bridge.py --help
```

- `--port` - Port to run on (default: 8000)
- `--host` - Host to bind to (default: 127.0.0.1)
- `--no-ngrok` - Disable automatic ngrok tunnel

**Environment variables:**
- `LOG_LEVEL` - Logging level (default: INFO)

## Manual Setup

If you prefer manual ngrok control:

```bash
# Start without ngrok
python context7_bridge.py --no-ngrok

# In another terminal
ngrok http 8000
```

## Testing

Test without ChatGPT:

```bash
# Health check
curl http://localhost:8000/health

# Test search
curl -X POST http://localhost:8000/sse \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search","arguments":{"query":"react"}}}'
```

## Troubleshooting

**"Could not get response from Context7 server"**
- Ensure Node.js and npx are installed and in PATH

**"Unknown document ID"**
- Always call `search` before `fetch` to get valid IDs
- Or use direct Context7 library IDs (starting with `/`)
- Note: Tool descriptions may need refinement for ChatGPT to better understand the search-first workflow - currently works but ChatGPT occasionally has hiccups with the sequence

**Debug mode:**
```bash
LOG_LEVEL=DEBUG python context7_bridge.py
```