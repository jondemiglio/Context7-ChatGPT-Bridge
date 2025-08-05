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

from fastapi import FastAPI, Request
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
        self.request_id += 1
        return self.request_id

    def _call_context7(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        try:
            init_request = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ChatGPT-Context7-Bridge", "version": "1.0.0"}
                }
            }
            initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            tool_request = {
                "jsonrpc": "2.0",
                "id": self._get_request_id(),
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
            input_data = (
                json.dumps(init_request) + "\n" +
                json.dumps(initialized_notification) + "\n" +
                json.dumps(tool_request) + "\n"
            )
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
                    last_error = f"Command {cmd[0]} failed: returncode={result.returncode}"
                except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                    last_error = f"Command {cmd[0]} error: {e}"
                    continue
                except Exception as e:
                    last_error = f"Unexpected error with {cmd[0]}: {e}"
                    continue
            if not result or not result.stdout:
                return f"Could not get response from Context7 server. Last error: {last_error}"
            if result.returncode != 0:
                logger.error(f"Context7 server error: {result.stderr}")
                return f"Error calling Context7: {result.stderr}"
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                try:
                    response = json.loads(line)
                    if response.get("id") == self.request_id and "result" in response:
                        content = response["result"].get("content", [])
                        if content and content[0].get("type") == "text":
                            return content[0]["text"]
                except json.JSONDecodeError:
                    continue
            return "No valid response from Context7 server"
        except Exception as e:
            logger.error(f"Error calling Context7: {e}")
            return f"Error calling Context7: {e}"

    def resolve_library_id(self, library_name: str) -> str:
        return self._call_context7("resolve-library-id", {"libraryName": library_name})

    def get_library_docs(self, library_id: str, topic: Optional[str] = None, tokens: int = 10000) -> str:
        args = {"context7CompatibleLibraryID": library_id, "tokens": tokens}
        if topic:
            args["topic"] = topic
        return self._call_context7("get-library-docs", args)

class ChatGPTContext7Bridge:
    def __init__(self):
        self.context7 = Context7Client()
        self.search_cache: Dict[str, Any] = {}

    def parse_library_info(self, response_text: str) -> List[Dict[str, Any]]:
        results = []
        try:
            lines = response_text.split('\n')
            current = {}
            for line in lines:
                line = line.strip()
                if line.startswith('- Title:'):
                    if current.get('id'):
                        results.append(current)
                    current = {"title": line.replace('- Title:', '').strip()}
                elif line.startswith('- Context7-compatible library ID:'):
                    lib_id = line.replace('- Context7-compatible library ID:', '').strip()
                    current.update({"id": lib_id, "library_id": lib_id})
                elif line.startswith('- Description:'):
                    current['text'] = line.replace('- Description:', '').strip()
                elif line.startswith('- Code Snippets:'):
                    current['snippets'] = line.replace('- Code Snippets:', '').strip()
                elif line.startswith('- Trust Score:'):
                    current['trust_score'] = line.replace('- Trust Score:', '').strip()
            if current.get('id'):
                results.append(current)
        except Exception as e:
            logger.error(f"Error parsing Context7 response: {e}")
        return results[:10]

    def search(self, query: str) -> Dict[str, Any]:
        try:
            logger.info(f"Searching for: {query}")
            # Determine if direct ID query
            if query.startswith('/') and '/' in query[1:]:
                docs = self.context7.get_library_docs(query, tokens=100)
                if "Error calling Context7" in docs:
                    return {"results": []}
                rid = hashlib.md5(f"{query}:direct".encode()).hexdigest()
                self.search_cache[rid] = {"library_id": query, "query": query}
                return {"results": [{"id": rid, "title": query, "text": docs, "url": f"https://context7.com{query}"}]}  
            # Normal search
            resp = self.context7.resolve_library_id(query)
            if "Error calling Context7" in resp:
                return {"results": []}
            libs = self.parse_library_info(resp)
            results = []
            for lib in libs:
                if not lib.get('id'): continue
                rid = hashlib.md5(f"{lib['id']}:{query}".encode()).hexdigest()
                self.search_cache[rid] = {"library_id": lib['id'], "query": query}
                desc = lib.get('text', '')
                meta = []
                if lib.get('snippets'): meta.append(f"Snippets: {lib['snippets']}")
                if lib.get('trust_score'): meta.append(f"Trust: {lib['trust_score']}")
                content = f"{desc}\n[{' | '.join(meta)}]\nID: {lib['id']}"
                results.append({"id": rid, "title": lib['title'], "text": content, "url": f"https://context7.com{lib['id']}"})
            return {"results": results}
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"results": []}

    def fetch(self, id: str) -> Dict[str, Any]:
        try:
            logger.info(f"Fetching document: {id}")
            parts = id.split('|')
            base = parts[0]
            topic = None
            tokens = 10000
            for p in parts[1:]:
                if p.startswith('topic:'): topic = p.split(':',1)[1]
                if p.startswith('tokens:'):
                    try: tokens = max(int(p.split(':',1)[1]), 10000)
                    except: pass
            if base in self.search_cache:
                lib_id = self.search_cache[base]['library_id']
            else:
                lib_id = base
            docs = self.context7.get_library_docs(lib_id, topic=topic, tokens=tokens)
            return {"id": id, "title": base, "text": docs, "url": f"https://context7.com{lib_id}"}
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            raise ValueError(f"Failed to fetch: {e}")

# Instantiate
bridge = ChatGPTContext7Bridge()
app = FastAPI(title="ChatGPT Context7 MCP Bridge")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Alias MCP endpoints for ChatGPT UI health check
@app.post("/search")
async def mcp_search(request: Request):
    return await app(scope=request.scope, receive=request.receive, send=request.send)

@app.post("/fetch")
async def mcp_fetch(request: Request):
    return await app(scope=request.scope, receive=request.receive, send=request.send)

# JSON-RPC SSE endpoint
@app.post("/sse")
async def sse_endpoint(request: Dict[str, Any]):
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return {"jsonrpc":"2.0","id":request_id,"result": {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"Context7 Documentation Search","version":"1.0.0"}}}
    elif method == "tools/list":
        return {"jsonrpc":"2.0","id":request_id,"result": {"tools": [
            {"name":"search","description":"Search Context7 docs","inputSchema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}},
            {"name":"fetch","description":"Fetch doc by ID","inputSchema":{"type":"object","properties":{"id":{"type":"string"}},"required":["id"]}}
        ]}}
    elif method == "tools/call":
        tool = request.get("params",{}).get("name")
        args = request.get("params",{}).get("arguments",{})
        try:
            if tool == "search":
                result = bridge.search(args.get("query",""))
            elif tool == "fetch":
                result = bridge.fetch(args.get("id",""))
            else:
                raise ValueError(f"Unknown tool {tool}")
            return {"jsonrpc":"2.0","id":request_id,"result":{"content":[{"type":"text","text":json.dumps(result)}]}}
        except Exception as e:
            return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32603,"message":str(e)}}
    return {"jsonrpc":"2.0","id":request_id,"error":{"code":-32601,"message":f"Method not found: {method}"}}

# Health endpoints
@app.get("/health")
async def health():
    return {"status":"healthy"}

@app.get("/")
async def root():
    return {"message":"ChatGPT Context7 MCP Bridge","sse_endpoint":"/sse"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("context7_bridge:app", host="0.0.0.0", port=port)
