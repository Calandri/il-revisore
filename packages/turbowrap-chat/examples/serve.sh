#!/bin/bash
# Serve the examples directory for testing

cd "$(dirname "$0")/.."

echo "Starting local server for @turbowrap/chat examples..."
echo ""
echo "Open in browser: http://localhost:3333/examples/basic.html"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Use Python's built-in HTTP server
python3 -m http.server 3333
