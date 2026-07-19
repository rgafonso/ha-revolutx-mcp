#!/usr/bin/env node

const http = require('http');
const { spawn } = require('child_process');
const readline = require('readline');

const PORT = process.env.PORT || 5000;
const MCP_BINARY = '/app/mcp/dist/index.js';

let mcpProcess = null;
let rl = null;

// Start the MCP server as a child process
function startMCPServer() {
  console.log('[INFO] Starting MCP server process...');
  mcpProcess = spawn('node', [MCP_BINARY], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env,
  });

  // Create readline interface for stdout
  rl = readline.createInterface({
    input: mcpProcess.stdout,
    output: process.stdout,
    terminal: false,
  });

  // Log MCP server errors
  mcpProcess.stderr.on('data', (data) => {
    console.error(`[MCP-ERROR] ${data.toString().trim()}`);
  });

  mcpProcess.on('error', (err) => {
    console.error(`[MCP-PROCESS-ERROR] ${err.message}`);
  });

  mcpProcess.on('exit', (code, signal) => {
    console.error(`[MCP-EXIT] Process exited with code ${code}, signal ${signal}`);
    process.exit(1);
  });
}

// Create HTTP server
function createHTTPServer() {
  const server = http.createServer(async (req, res) => {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
      res.writeHead(200);
      res.end();
      return;
    }

    if (req.method === 'GET' && req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
      return;
    }

    if (req.method === 'POST' && req.url === '/rpc') {
      let body = '';
      req.on('data', (chunk) => {
        body += chunk.toString();
      });

      req.on('end', () => {
        try {
          const message = JSON.parse(body);
          console.log(`[RPC-IN] ${JSON.stringify(message).substring(0, 100)}`);

          // Send message to MCP server stdin
          mcpProcess.stdin.write(JSON.stringify(message) + '\n');

          // Wait for response from MCP server stdout
          const handler = (line) => {
            try {
              const response = JSON.parse(line);
              console.log(`[RPC-OUT] ${JSON.stringify(response).substring(0, 100)}`);
              
              res.writeHead(200, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify(response));
              
              // Remove this handler after response
              rl.removeListener('line', handler);
            } catch (err) {
              console.error(`[PARSE-ERROR] ${err.message}`);
            }
          };

          rl.once('line', handler);

          // Timeout if no response within 30 seconds
          setTimeout(() => {
            rl.removeListener('line', handler);
            res.writeHead(504, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'MCP server timeout' }));
          }, 30000);
        } catch (err) {
          console.error(`[ERROR] ${err.message}`);
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: err.message }));
        }
      });
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  });

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`[INFO] HTTP MCP bridge listening on port ${PORT}`);
  });

  server.on('error', (err) => {
    console.error(`[SERVER-ERROR] ${err.message}`);
    process.exit(1);
  });
}

// Start everything
startMCPServer();
createHTTPServer();

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('[INFO] SIGTERM received, shutting down...');
  if (mcpProcess) {
    mcpProcess.kill('SIGTERM');
  }
  process.exit(0);
});

console.log('[INFO] Revolut X MCP network transport bridge initialized');
