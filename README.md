# Context7 ChatGPT Bridge

A production-ready bridge that allows ChatGPT to use the Context7 MCP server for accessing up-to-date programming documentation. This bridge implements ChatGPT's required `search` and `fetch` tools while internally using Context7's `resolve-library-id` and `get-library-docs` tools.

## Features

- **ChatGPT Compatible**: Implements the exact search/fetch specification required by ChatGPT MCP connectors
- **Context7 Integration**: Uses the official Context7 MCP server (`@upstash/context7-mcp`) for documentation
- **Advanced Parameter Support**: Supports topic-focused searches and custom token limits
- **Direct Library ID Support**: Can work with Context7 library IDs directly (e.g., `/reactjs/react.dev`)
- **Cross-Platform**: Works on Windows, Linux, and macOS

## Requirements

- **Node.js** >= 18.0.0 (for Context7 MCP server)
- **Python** >= 3.8
- **Internet connection**

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the bridge with automatic ngrok:**
   ```bash
   python context7_bridge.py
   ```
   
   The script will automatically:
   - Start the bridge server on port 8000
   - Launch ngrok tunnel
   - Display the ChatGPT-ready URL

3. **Copy the URL to ChatGPT:**
   The script will show you the exact URL to add to ChatGPT's MCP connector:
   ```
   https://abc123.ngrok-free.app/sse
   ```

### Alternative: Manual ngrok

If you prefer manual control:

```bash
# Start without ngrok
python context7_bridge.py --no-ngrok

# In another terminal
ngrok http 8000
```

## Usage

### ChatGPT Integration

Add your ngrok URL to ChatGPT's MCP connectors:

```json
{
  "name": "Context7 Documentation",
  "url": "https://your-ngrok-url.ngrok-free.app/sse",
  "description": "Access up-to-date documentation for programming libraries"
}
```

### Available Tools

The bridge exposes two tools that ChatGPT can use:

#### 1. `search`
- Search for programming libraries and frameworks
- Supports both library names (e.g., "React", "MongoDB") and direct Context7 library IDs (e.g., "/reactjs/react.dev")
- Returns detailed metadata including trust scores and documentation coverage

#### 2. `fetch`
- Fetch comprehensive documentation for specific libraries
- Supports advanced parameter syntax for focused documentation:
  - Basic: `library_id`
  - Topic-focused: `library_id|topic:hooks`
  - Custom tokens: `library_id|tokens:15000`
  - Combined: `library_id|topic:authentication|tokens:12000`

### Example Topics

- `hooks` - React hooks, custom hooks, useEffect, useState
- `routing` - Navigation, route setup, dynamic routes
- `authentication` - Login, security, JWT, OAuth
- `installation` - Setup, configuration, getting started
- `api` - API reference, methods, endpoints
- `examples` - Code examples, tutorials, implementations

## How It Works

1. **ChatGPT** sends search/fetch requests to your bridge via ngrok
2. **Bridge** translates these to Context7's resolve-library-id/get-library-docs calls
3. **Context7** returns up-to-date documentation from their database
4. **Bridge** formats responses in ChatGPT's expected format

## Architecture

```
ChatGPT → ngrok → Bridge → Context7 MCP Server → Documentation Database
                    ↓
              search/fetch tools ← resolve-library-id/get-library-docs
```

## Configuration

The bridge supports several command-line options:

```bash
python context7_bridge.py --help
```

Options:
- `--port` - Port to run on (default: 8000)
- `--host` - Host to bind to (default: 127.0.0.1)
- `--no-ngrok` - Disable automatic ngrok tunnel

Environment variables:
- `LOG_LEVEL` - Logging level (default: INFO)

## Development

### Testing Locally

Test the bridge without ChatGPT:

```bash
# Start the bridge
python context7_bridge.py --port 8000

# Test health endpoint
curl http://localhost:8000/health

# Test search
curl -X POST http://localhost:8000/sse \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search","arguments":{"query":"react"}}}'
```

### Code Structure

- **Context7Client**: Handles subprocess communication with Context7 MCP server
- **ChatGPTContext7Bridge**: Implements search/fetch logic and parameter parsing
- **FastAPI app**: Provides SSE endpoint for ChatGPT compatibility

## Troubleshooting

### Common Issues

1. **"Could not get response from Context7 server"**
   - Ensure Node.js and npx are installed and in PATH
   - Check internet connection for Context7 package download

2. **"Unknown document ID"**
   - Always call `search` before `fetch` to get valid IDs
   - Or use direct Context7 library IDs (starting with `/`)

3. **ngrok connection issues**
   - Verify ngrok is running and accessible
   - Check that the bridge port is available

### Debug Mode

Enable debug logging:

```bash
LOG_LEVEL=DEBUG python context7_bridge.py
```
