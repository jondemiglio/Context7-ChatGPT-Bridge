#!/usr/bin/env python3
"""
ChatGPT-Compatible Context7 MCP Bridge
Implements ChatGPT's search/fetch specification while using Context7 internally.
"""

import json
import logging
import os
import subprocess
import hashlib
import threading
import time
import signal
import sys
from typing import Dict, Any, Optional, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Context7Client:
    """Client for calling Context7 MCP server."""
    
    def __init__(self):
        self.request_id = 1
        
    def _get_request_id(self):
        """Get next request ID."""
        self.request_id += 1
        return self.request_id
    
    def _call_context7(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call Context7 MCP server directly using subprocess."""
        try:
            # Create MCP requests
            init_request = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "ChatGPT-Context7-Bridge",
                        "version": "1.0.0"
                    }
                }
            }
            
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            
            tool_request = {
                "jsonrpc": "2.0",
                "id": self._get_request_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            # Prepare input for Context7 server
            input_data = (
                json.dumps(init_request) + "\n" +
                json.dumps(initialized_notification) + "\n" +
                json.dumps(tool_request) + "\n"
            )
            
            # Call Context7 MCP server - try different npx paths
            npx_commands = [
                ["npx", "-y", "@upstash/context7-mcp", "--transport", "stdio"],
                ["C:\\Program Files\\nodejs\\npx.cmd", "-y", "@upstash/context7-mcp", "--transport", "stdio"],
                ["C:\\Users\\S\\AppData\\Roaming\\npm\\npx.cmd", "-y", "@upstash/context7-mcp", "--transport", "stdio"],
                ["wsl", "npx", "-y", "@upstash/context7-mcp", "--transport", "stdio"]
            ]
            
            result = None
            last_error = None
            for cmd in npx_commands:
                try:
                    logger.debug(f"Trying command: {cmd}")
                    result = subprocess.run(
                        cmd,
                        input=input_data,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        timeout=60
                    )
                    
                    if result.returncode == 0 and result.stdout:
                        break
                    else:
                        last_error = f"Command {cmd[0]} failed: returncode={result.returncode}"
                        
                except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                    last_error = f"Command {cmd[0]} error: {str(e)}"
                    continue
                except Exception as e:
                    last_error = f"Unexpected error with {cmd[0]}: {str(e)}"
                    continue
            
            if not result or not result.stdout:
                return f"Could not get response from Context7 server. Last error: {last_error}"
            
            if result.returncode != 0:
                logger.error(f"Context7 server error: {result.stderr}")
                return f"Error calling Context7: {result.stderr}"
            
            # Parse responses
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line.strip():
                    try:
                        response = json.loads(line)
                        # Look for tool response
                        if (response.get("id") == self.request_id and 
                            "result" in response):
                            content = response["result"].get("content", [])
                            if content and content[0].get("type") == "text":
                                return content[0]["text"]
                    except json.JSONDecodeError:
                        continue
            
            return "No valid response from Context7 server"
            
        except subprocess.TimeoutExpired:
            return "Timeout calling Context7 server"
        except Exception as e:
            logger.error(f"Error calling Context7: {e}")
            return f"Error calling Context7: {str(e)}"
    
    def resolve_library_id(self, library_name: str) -> str:
        """Call Context7's resolve-library-id tool."""
        return self._call_context7("resolve-library-id", {"libraryName": library_name})
    
    def get_library_docs(self, library_id: str, topic: Optional[str] = None, tokens: int = 10000) -> str:
        """Call Context7's get-library-docs tool."""
        arguments = {
            "context7CompatibleLibraryID": library_id,
            "tokens": tokens
        }
        
        if topic:
            arguments["topic"] = topic
        
        return self._call_context7("get-library-docs", arguments)


class ChatGPTContext7Bridge:
    """Bridge that implements ChatGPT's search/fetch specification using Context7."""
    
    def __init__(self):
        self.context7 = Context7Client()
        self.search_cache = {}  # Cache search results for fetch
    
    def parse_library_info(self, context7_response: str) -> List[Dict[str, Any]]:
        """Parse Context7 resolve-library-id response into search results."""
        results = []
        
        try:
            # Parse the Context7 response text
            lines = context7_response.split('\n')
            current_library = {}
            
            for line in lines:
                line = line.strip()
                if line.startswith('- Title:'):
                    # Save previous library if it exists
                    if current_library and current_library.get('id'):
                        results.append(current_library)
                    
                    # Start new library
                    title = line.replace('- Title:', '').strip()
                    current_library = {"title": title}
                    
                elif line.startswith('- Context7-compatible library ID:'):
                    library_id = line.replace('- Context7-compatible library ID:', '').strip()
                    current_library["id"] = library_id
                    current_library["library_id"] = library_id
                    
                elif line.startswith('- Description:'):
                    description = line.replace('- Description:', '').strip()
                    current_library["text"] = description
                    
                elif line.startswith('- Code Snippets:'):
                    snippets = line.replace('- Code Snippets:', '').strip()
                    current_library["snippets"] = snippets
                    
                elif line.startswith('- Trust Score:'):
                    score = line.replace('- Trust Score:', '').strip()
                    current_library["trust_score"] = score
            
            # Add last library
            if current_library and current_library.get('id'):
                results.append(current_library)
                
        except Exception as e:
            logger.error(f"Error parsing Context7 response: {e}")
        
        return results[:10]  # Limit to top 10 results
    
    def search(self, query: str) -> Dict[str, Any]:
        """Implement ChatGPT's search specification."""
        try:
            logger.info(f"Searching for: {query}")
            
            # Check if query is a Context7 library ID (e.g., '/reactjs/react.dev')
            if query.startswith('/') and '/' in query[1:]:
                logger.info(f"Query appears to be a Context7 library ID: {query}")
                # For library ID queries, we'll try to get docs to verify existence
                # and create a single result entry
                test_docs = self.context7.get_library_docs(query, tokens=100)
                
                if "Error calling Context7" in test_docs or "No documentation found" in test_docs:
                    return {"results": []}
                
                # Create a single result for the specified library ID
                result_id = hashlib.md5(f"{query}:direct".encode()).hexdigest()
                
                # Cache the library info
                self.search_cache[result_id] = {
                    "library_id": query,
                    "query": query,
                    "title": query.split('/')[-1].replace('-', ' ').title(),
                    "description": f"Direct Context7 library access for {query}",
                    "snippets": "Available",
                    "trust_score": "Verified"
                }
                
                result = {
                    "id": result_id,
                    "title": f"Direct Library Access: {query}",
                    "text": f"Context7-compatible library ID: {query}\nDirect access verified - documentation available.\nUse fetch tool to retrieve full documentation.",
                    "url": f"https://context7.com{query}"
                }
                
                return {"results": [result]}
            
            # Regular library name search
            library_name = query
            
            # Get library options from Context7
            context7_response = self.context7.resolve_library_id(library_name)
            
            if "No matching libraries found" in context7_response or "Error calling Context7" in context7_response:
                return {"results": []}
            
            # Parse the Context7 response into search results
            libraries = self.parse_library_info(context7_response)
            
            # Convert to ChatGPT's expected format
            results = []
            for lib in libraries:
                if not lib.get('id') or not lib.get('title'):
                    continue
                    
                # Create unique search result ID
                result_id = hashlib.md5(f"{lib['id']}:{query}".encode()).hexdigest()
                
                # Cache the library info for later fetch
                self.search_cache[result_id] = {
                    "library_id": lib["id"],
                    "query": query,
                    "title": lib.get("title", ""),
                    "description": lib.get("text", ""),
                    "snippets": lib.get("snippets", "0"),
                    "trust_score": lib.get("trust_score", "0")
                }
                
                # Create rich description with Context7 details
                description_parts = []
                if lib.get("text"):
                    description_parts.append(lib["text"])
                
                # Add Context7-specific metadata
                context7_info = []
                if lib.get("snippets"):
                    context7_info.append(f"Code Snippets: {lib['snippets']}")
                if lib.get("trust_score"):
                    context7_info.append(f"Trust Score: {lib['trust_score']}")
                
                if context7_info:
                    description_parts.append(f"\n[{' | '.join(context7_info)}]")
                    
                description_parts.append(f"\nContext7 Library ID: {lib['id']}")
                description_parts.append("\nUse the fetch tool with this result's ID to get full documentation. Add '|topic:your_topic' for focused docs.")
                
                # Format for ChatGPT
                result = {
                    "id": result_id,
                    "title": f"{lib.get('title', 'Unknown Library')} ({lib['id']})",
                    "text": "".join(description_parts),
                    "url": f"https://context7.com{lib['id']}" if lib.get('id') else None
                }
                
                results.append(result)
            
            logger.info(f"Found {len(results)} results for query: {query}")
            return {"results": results}
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"results": []}
    
    def fetch(self, id: str) -> Dict[str, Any]:
        """Implement ChatGPT's fetch specification with Context7 parameters."""
        try:
            logger.info(f"Fetching document: {id}")
            
            # Parse advanced parameters from id
            # Format: "base_id|topic:hooks|tokens:15000"
            parts = id.split('|')
            base_id = parts[0]
            topic = None
            tokens = 10000
            
            # Parse optional parameters
            for part in parts[1:]:
                if part.startswith('topic:'):
                    topic = part.replace('topic:', '').strip()
                elif part.startswith('tokens:'):
                    try:
                        tokens = int(part.replace('tokens:', '').strip())
                        tokens = max(tokens, 10000)  # Context7 minimum
                    except ValueError:
                        pass
            
            logger.info(f"Parsed fetch parameters: base_id={base_id}, topic={topic}, tokens={tokens}")
            
            # Check if this is a direct Context7 library ID or a search result ID
            if base_id.startswith('/') and '/' in base_id[1:]:
                # Direct Context7 library ID (e.g., '/mongodb/docs', '/vercel/next.js')
                library_id = base_id
                cached_info = {
                    "title": base_id.split('/')[-1].title(),
                    "query": base_id,
                    "snippets": "Unknown",
                    "trust_score": "Unknown"
                }
                logger.info(f"Using direct Context7 library ID: {library_id}")
            else:
                # Search result ID
                if base_id not in self.search_cache:
                    raise ValueError(f"Unknown document ID: {base_id}. Please search first to get valid IDs.")
                
                cached_info = self.search_cache[base_id]
                library_id = cached_info["library_id"]
            
            # Use provided topic or fallback to original query
            fetch_topic = topic if topic else cached_info.get("query")
            
            # Get full documentation from Context7 with parameters
            docs = self.context7.get_library_docs(
                library_id=library_id, 
                topic=fetch_topic, 
                tokens=tokens
            )
            
            if "Error calling Context7" in docs:
                raise ValueError(f"Failed to fetch documentation: {docs}")
            
            # Create descriptive title
            title_parts = [cached_info['title']]
            if topic:
                title_parts.append(f"- {topic.title()}")
            title_parts.append("Documentation")
            
            # Format for ChatGPT
            result = {
                "id": id,
                "title": " ".join(title_parts),
                "text": docs,
                "url": f"https://context7.com{library_id}",
                "metadata": {
                    "library_id": library_id,
                    "context7_compatible_id": library_id,
                    "topic": fetch_topic,
                    "tokens_requested": tokens,
                    "original_query": cached_info.get("query"),
                    "snippets_available": cached_info.get("snippets", "0"),
                    "trust_score": cached_info.get("trust_score", "0"),
                    "source": "Context7 MCP Server",
                    "documentation_length": len(docs)
                }
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            raise ValueError(f"Failed to fetch document: {str(e)}")


# Global bridge instance
bridge = ChatGPTContext7Bridge()

# FastAPI app for ChatGPT SSE endpoint
app = FastAPI(title="ChatGPT Context7 MCP Bridge")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/sse")
async def sse_endpoint(request: dict):
    """SSE endpoint for ChatGPT MCP connector - JSON-RPC 2.0"""
    
    method = request.get("method")
    request_id = request.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "Context7 Documentation Search",
                    "version": "1.0.0"
                }
            }
        }
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "search",
                        "description": "Purpose:\\n  1. Search for programming libraries, frameworks, and packages in the Context7 documentation database.\\n  2. Resolve general library names into Context7-compatible library IDs with detailed metadata.\\n  3. You MUST call this function before 'fetch' to obtain valid Context7-compatible library IDs UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version'.\\n\\nUsage:\\n  1. Search by library name to discover available libraries and their Context7 IDs (e.g., 'React', 'Next.js', 'MongoDB', 'Prisma').\\n  2. Search with specific Context7 library ID to verify existence and get metadata (e.g., '/reactjs/react.dev', '/vercel/next.js').\\n  3. Use partial names for discovery (e.g., 'mongo' finds MongoDB libraries, 'tail' finds Tailwind).\\n  4. Search results prioritize exact matches, then relevance, trust scores (7-10 are most authoritative), and documentation coverage.\\n\\nSearch Response Format:\\n  1. Each result includes: Context7-compatible library ID, library name, description, code snippets count, trust score.\\n  2. Results are ranked by relevance and trust score for optimal selection.\\n  3. If multiple good matches exist, all are returned for user selection.\\n  4. If no matches found, suggestions for query refinements are provided.\\n\\nLibrary Selection Guidelines:\\n  • Prioritize libraries with higher trust scores (9-10 are most reliable)\\n  • Consider code snippet count as indicator of documentation completeness\\n  • Exact name matches take precedence over partial matches\\n  • Official libraries (e.g. /reactjs/react.dev) are preferred over community versions",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Library name to search for (e.g., 'React', 'mongodb', 'tailwind') OR exact Context7-compatible library ID to verify (e.g., '/reactjs/react.dev', '/vercel/next.js'). Supports partial names for discovery."
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "fetch",
                        "description": "Purpose:\\n  1. Fetch comprehensive, up-to-date documentation for programming libraries using Context7-compatible library IDs.\\n  2. Retrieve focused documentation on specific topics within a library.\\n  3. Control documentation depth and detail level through token limits.\\n\\nUsage Requirements:\\n  1. You MUST call 'search' first to obtain valid Context7-compatible library IDs UNLESS the user explicitly provides a library ID in the format '/org/project' or '/org/project/version'.\\n  2. Use the exact library ID returned from search results or provided by the user.\\n\\nAdvanced Parameter Syntax:\\n  • Basic fetch: Use library ID directly (e.g., 'abc123' from search results, or '/reactjs/react.dev')\\n  • Topic-focused documentation: Append '|topic:your_topic' (e.g., 'abc123|topic:hooks', '/reactjs/react.dev|topic:routing')\\n  • Custom token limit: Append '|tokens:number' (e.g., 'abc123|tokens:15000', minimum 10000)\\n  • Combined parameters: 'abc123|topic:authentication|tokens:12000'\\n\\nTopic Examples:\\n  • 'hooks' - React hooks, custom hooks, useEffect, useState\\n  • 'routing' - Navigation, route setup, dynamic routes\\n  • 'authentication' - Login, security, JWT, OAuth\\n  • 'installation' - Setup, configuration, getting started\\n  • 'api' - API reference, methods, endpoints\\n  • 'examples' - Code examples, tutorials, implementations\\n\\nDocumentation Response:\\n  1. Returns complete documentation including installation instructions, usage examples, API references, best practices.\\n  2. Focused topic requests return relevant sections with detailed explanations and working code snippets.\\n  3. Higher token limits provide more comprehensive coverage and additional examples.\\n  4. All documentation is current and sourced from official library maintainers.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Context7-compatible library ID from search results (e.g., 'abc123') OR exact library ID (e.g., '/mongodb/docs', '/vercel/next.js', '/supabase/supabase'). Advanced syntax: append '|topic:hooks|tokens:15000' for focused, detailed documentation. Topic values: 'hooks', 'routing', 'authentication', 'installation', 'api', 'examples', 'configuration', 'testing'."
                                }
                            },
                            "required": ["id"]
                        }
                    }
                ]
            }
        }
    
    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name")
        arguments = request.get("params", {}).get("arguments", {})
        
        try:
            if tool_name == "search":
                query = arguments.get("query", "")
                result = bridge.search(query)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2)
                            }
                        ]
                    }
                }
            
            elif tool_name == "fetch":
                doc_id = arguments.get("id", "")
                result = bridge.fetch(doc_id)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2)
                            }
                        ]
                    }
                }
            
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name}"
                    }
                }
                
        except Exception as e:
            logger.error(f"Tool call error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Tool execution failed: {str(e)}"
                }
            }
    
    elif method == "notifications/initialized":
        return None  # No response needed for notifications
    
    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}"
        }
    }

@app.get("/sse")
async def sse_get_endpoint():
    """GET endpoint to show server is running"""
    return {
        "name": "Context7 Documentation Search",
        "version": "1.0.0",
        "transport": "sse",
        "status": "running",
        "tools": ["search", "fetch"]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ChatGPT Context7 MCP Bridge"}

@app.get("/")
async def root():
    return {"message": "ChatGPT Context7 MCP Bridge", "sse_endpoint": "/sse"}


class NgrokManager:
    """Manages ngrok tunnel for the bridge."""
    
    def __init__(self, port: int):
        self.port = port
        self.process = None
        self.tunnel_url = None
        
    def start(self):
        """Start ngrok tunnel."""
        try:
            logger.info("Starting ngrok tunnel...")
            
            # Try different ngrok commands
            ngrok_commands = [
                ["ngrok", "http", str(self.port)],
                ["C:\\Program Files\\ngrok\\ngrok.exe", "http", str(self.port)],
                ["wsl", "ngrok", "http", str(self.port)]
            ]
            
            for cmd in ngrok_commands:
                try:
                    logger.debug(f"Trying ngrok command: {cmd}")
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    
                    # Give ngrok time to start
                    time.sleep(3)
                    
                    # Check if process is still running
                    if self.process.poll() is None:
                        # Try to get tunnel URL from ngrok API
                        self._get_tunnel_url()
                        if self.tunnel_url:
                            logger.info(f"✅ ngrok tunnel started: {self.tunnel_url}")
                            logger.info(f"🔗 ChatGPT SSE endpoint: {self.tunnel_url}/sse")
                            return True
                        
                except (FileNotFoundError, subprocess.SubprocessError) as e:
                    logger.debug(f"Failed to start ngrok with {cmd[0]}: {e}")
                    continue
                    
            logger.warning("⚠️  Could not start ngrok automatically")
            logger.info(f"💡 Please start ngrok manually: ngrok http {self.port}")
            return False
            
        except Exception as e:
            logger.error(f"Error starting ngrok: {e}")
            return False
    
    def _get_tunnel_url(self):
        """Get tunnel URL from ngrok API."""
        try:
            import urllib.request
            import json
            
            # Query ngrok API for tunnels
            with urllib.request.urlopen("http://localhost:4040/api/tunnels") as response:
                data = json.loads(response.read())
                
            for tunnel in data.get("tunnels", []):
                if tunnel.get("proto") == "https":
                    self.tunnel_url = tunnel["public_url"]
                    break
                    
        except Exception as e:
            logger.debug(f"Could not get ngrok tunnel URL: {e}")
    
    def stop(self):
        """Stop ngrok tunnel."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                logger.info("ngrok tunnel stopped")
            except subprocess.TimeoutExpired:
                self.process.kill()
                logger.warning("Force killed ngrok process")
            except Exception as e:
                logger.error(f"Error stopping ngrok: {e}")


# Global ngrok manager
ngrok_manager = None


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global ngrok_manager
    logger.info("\n🛑 Shutting down...")
    
    if ngrok_manager:
        ngrok_manager.stop()
    
    sys.exit(0)


def main():
    """Main entry point for the server."""
    global ngrok_manager
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ChatGPT-Compatible Context7 MCP Bridge'
    )
    parser.add_argument(
        '--port', 
        type=int, 
        default=8000,
        help='Port for SSE transport (default: 8000)'
    )
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--no-ngrok',
        action='store_true',
        help='Disable automatic ngrok tunnel'
    )
    
    args = parser.parse_args()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info(f"🚀 Starting ChatGPT-Compatible Context7 MCP Bridge")
    logger.info(f"🌐 Running on {args.host}:{args.port}")
    logger.info(f"📡 SSE endpoint: http://{args.host}:{args.port}/sse")
    
    # Test Context7 connection
    logger.info("🔍 Testing Context7 connection...")
    test_bridge = ChatGPTContext7Bridge()
    test_result = test_bridge.search("react")
    logger.info(f"✅ Context7 test found {len(test_result.get('results', []))} results")
    
    # Start ngrok if requested
    if not args.no_ngrok:
        ngrok_manager = NgrokManager(args.port)
        ngrok_started = ngrok_manager.start()
        
        if ngrok_started:
            logger.info("📋 Copy this URL to ChatGPT MCP connector:")
            logger.info(f"   {ngrok_manager.tunnel_url}/sse")
        else:
            logger.info("💡 Manual ngrok setup:")
            logger.info(f"   1. Run: ngrok http {args.port}")
            logger.info(f"   2. Copy the https URL + /sse to ChatGPT")
    else:
        logger.info("🚫 ngrok disabled - running local only")
    
    try:
        # Start the server
        logger.info("🎯 Bridge ready for ChatGPT connections!")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # bind to 0.0.0.0 so Railway’s load-balancer can connect
    app.run(host="0.0.0.0", port=port)

    main()
