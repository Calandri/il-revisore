# Debugging the /start Endpoint

This guide will help you troubleshoot why the Claude CLI process isn't starting when you create or select a chat.

## Quick Test (5 minutes)

### Option 1: Using the Test Script
```bash
cd /Users/niccolocalandri/code/ultraWrap
chmod +x test_start_endpoint.sh
./test_start_endpoint.sh
```

This will:
1. Create a new chat session
2. Call `/start` to spawn the process
3. Check `/context` and `/usage` to verify the process is running

Look for the `HTTP_CODE` in the output - should be:
- Step 3: `HTTP_CODE:200` (process started)
- Step 4: `HTTP_CODE:200` (context data available)
- Step 5: `HTTP_CODE:200` (usage data available)

If you see `HTTP_CODE:503`, the process didn't start. Continue below.

### Option 2: Manual Curl Test
```bash
# 1. Create session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/cli-chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"cli_type":"claude"}' | jq -r '.id')

echo "Session: $SESSION_ID"

# 2. Start process
curl -X POST "http://localhost:8000/api/cli-chat/sessions/$SESSION_ID/start" | jq '.'

# 3. Check if it worked
curl "http://localhost:8000/api/cli-chat/sessions/$SESSION_ID/context" | jq '.'
```

## Detailed Debugging

### Step 1: Check Server Logs

**Terminal 1 (running your server):**
```bash
# Look for [START] logs - watch for any ERROR or exception
grep -i "\[START\]" server.log | tail -50
```

**Key log messages to look for:**

✅ **Success sequence:**
```
[START] Received request to start session <session_id>
[START] Found session: cli_type=claude, status=idle
[START] Got process manager, checking for existing process
[START] No existing process, will spawn new one
[START] Generating context for session <session_id>
[START] Generated context for session <session_id>: 8523 chars
[START] CLI type: <CLIType.CLAUDE: 'claude'>
[START] Spawning Claude CLI process
[START] Working directory: /Users/niccolocalandri/code/ultraWrap
[START] Model: claude-opus-4-5-20251101
[START] Existing session ID: None
[START] Calling spawn_claude...
[START] spawn_claude returned, proc=<CLIProcess>, claude_session_id=<uuid>
[START] Successfully spawned claude process for session <session_id>
[START] Verification: process in manager._processes? True
```

❌ **Error patterns to look for:**

1. **Session not found:**
   ```
   [START] Session <session_id> not found in database
   ```
   → Check that the session was created properly

2. **Context generation failed:**
   ```
   [START] Generating context for session...
   [START] Failed to start process: ValueError: ...
   ```
   → Repository or branch info might be incorrect

3. **Process spawn failed:**
   ```
   [START] Calling spawn_claude...
   [START] Failed to start process: RuntimeError: ...
   ```
   → Check if Claude CLI is installed: `which claude`

4. **Permission/Path issues:**
   ```
   [START] Failed to start process: PermissionError: ...
   [START] Failed to start process: FileNotFoundError: ...
   ```
   → Check file permissions and paths

### Step 2: Check Frontend Console

**In your browser (F12 or Cmd+Option+I):**

Go to the Console tab and look for these messages:

✅ **Success:**
```
[createSession] Starting process for session: <session_id>
[createSession] Process started: {status: "started", session_id: "...", process_running: true, ...}
```

✅ **Or for existing sessions:**
```
[selectSession] Starting process for session: <session_id>
[selectSession] Process started: {status: "started", ...}
[chatSidebar] Session info loaded: {context: {...}, usage: {...}}
```

❌ **Failure patterns:**
```
[createSession] Start endpoint failed: {status: 500, statusText: "Internal Server Error", error: "..."}
[createSession] Error detail: Failed to start CLI process: ...
```

→ Look at the error detail message

```
[createSession] Failed to start process (network error): <error>
[createSession] Error details: {name: "...", message: "..."}
```

→ Network/fetch issue, not a server error

### Step 3: Verify Process is Running

```bash
# Check if Claude CLI process exists
ps aux | grep claude | grep -v grep

# Or use the process manager
lsof -p $(pgrep claude) 2>/dev/null || echo "No Claude process found"
```

### Step 4: Test Claude CLI Directly

```bash
# Make sure Claude CLI is installed and working
claude --version

# Try starting a simple Claude CLI session
claude --session-id test-123 --model claude-opus-4-5-20251101 \
  --output-format stream-json << EOF
Hello, test message
/context
/usage
EOF
```

This tests if Claude CLI itself works, independent of TurboWrap.

## Common Issues & Fixes

### Issue 1: `Process not found / Command not found`
```
[START] Failed to start process: FileNotFoundError: [Errno 2] No such file or directory: 'claude'
```

**Fix:** Install Claude CLI
```bash
npm install -g @anthropic-ai/cli
```

Or if you have it, verify the path:
```bash
which claude
export PATH="$PATH:$(npm prefix -g)/bin"
```

### Issue 2: `Permission denied`
```
[START] Failed to start process: PermissionError: [Errno 13] Permission denied
```

**Fix:** Check directory permissions
```bash
# Make sure working directory is readable
chmod 755 /Users/niccolocalandri/code/ultraWrap
```

### Issue 3: `Max processes reached`
```
[START] Failed to start process: RuntimeError: Max processes (10) reached
```

**Fix:** Increase max processes or kill existing ones
```bash
# Kill all Claude processes
pkill -f "claude --session-id"

# Or in code, increase _max_processes in ProcessManager
```

### Issue 4: `Repository not found`
```
[START] Failed to start process: ValueError: Repository with ID ... not found
```

**Fix:** Make sure you selected a repository when creating the chat

### Issue 5: API Key Issues
```
[START] Failed to start process: ... Invalid API key
```

**Fix:** Verify environment variables
```bash
echo $ANTHROPIC_API_KEY  # Should not be empty
env | grep ANTHROPIC
```

## Real-time Server Log Monitoring

Instead of manual checking, run this to watch logs in real-time:

```bash
# Terminal 1: Start server with verbose logging
uv run uvicorn src.turbowrap.api.main:app --reload --log-level debug 2>&1 | tee server.log

# Terminal 2: Watch for START logs
tail -f server.log | grep -E "\[START\]|\[ERROR\]"
```

## Network Request Tracing

If the issue is on the frontend, you can trace the actual network request:

**Browser DevTools Network tab:**
1. Open F12 → Network tab
2. Create a new chat or select existing chat
3. Look for POST request to `/api/cli-chat/sessions/<id>/start`
4. Click it and check:
   - **Status:** Should be 200
   - **Response:** Should show `{"status": "started", ...}`
   - **Headers:** Check for any auth/CORS issues

If you see a different status (like 500), click on the Response tab to see the error message.

## Getting Help

When reporting the issue, provide:

1. **Output of test script:**
   ```bash
   ./test_start_endpoint.sh 2>&1 | tee test_output.txt
   ```

2. **Server logs (last 100 lines):**
   ```bash
   tail -100 server.log | grep -E "\[START\]|\[ERROR\]|\[CLAUDE\]" > debug_logs.txt
   ```

3. **Browser console output:**
   - F12 → Console → Right-click → "Save as..."
   - Save as `console_output.txt`

4. **System info:**
   ```bash
   echo "=== System ===" && \
   uname -a && \
   echo "=== Claude CLI ===" && \
   which claude && claude --version && \
   echo "=== Node ===" && \
   node --version && npm --version && \
   echo "=== Python ===" && \
   python3 --version && \
   echo "=== Environment ===" && \
   env | grep -E "ANTHROPIC|GOOGLE|PYTHONPATH|PATH" | head -10
   ```

Provide all this info when asking for help.
