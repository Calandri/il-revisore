"""Shared test fixtures for turbowrap-llm."""

import pytest

# Sample Claude CLI stream-json output
CLAUDE_STREAM_JSON_SAMPLE = """{"type":"system","subtype":"init","session_id":"abc123","tools":["Read","Write"],"model":"claude-opus-4-5-20251101"}
{"type":"assistant","message":{"content":[{"type":"text","text":"Hello!"}]}}
{"type":"result","result":"Hello! How can I help you today?","duration_ms":1500,"duration_api_ms":1200,"num_turns":1,"total_cost_usd":0.05,"modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":100,"outputTokens":20,"cacheReadInputTokens":50,"cacheCreationInputTokens":0,"costUSD":0.03,"contextWindow":200000,"webSearchRequests":1},"claude-haiku-4-5-20251001":{"inputTokens":200,"outputTokens":30,"cacheReadInputTokens":0,"cacheCreationInputTokens":100,"costUSD":0.02,"contextWindow":100000}}}"""


# Sample Claude CLI output with tool use
CLAUDE_TOOL_USE_SAMPLE = """{"type":"system","subtype":"init","session_id":"xyz789"}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","id":"tool_1"},{"type":"tool_use","name":"Task","id":"tool_2"},{"type":"tool_use","name":"Task","id":"tool_3"}]}}
{"type":"result","result":"Done!","duration_ms":5000,"duration_api_ms":4000,"num_turns":3,"modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":500,"outputTokens":100,"costUSD":0.1}}}"""


# Sample Claude CLI output with thinking
CLAUDE_THINKING_SAMPLE = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Let me analyze this..."},{"type":"text","text":"Here's my answer"}]}}
{"type":"result","result":"Here's my answer","duration_ms":2000,"modelUsage":{}}"""


# Sample Claude CLI error output
CLAUDE_ERROR_SAMPLE = """{"type":"result","result":"API rate limit exceeded","is_error":true,"modelUsage":{}}"""


# Sample Gemini CLI stream-json output
GEMINI_STREAM_JSON_SAMPLE = """{"type":"init","sessionId":"gemini-123"}
{"type":"text","content":"Hello from Gemini!"}
{"type":"result","stats":{"total_tokens":1500,"input_tokens":1200,"output_tokens":300,"cached":100,"duration_ms":2000,"tool_calls":2},"result":"Hello from Gemini!"}"""


# Sample Grok CLI JSONL output
GROK_JSONL_SAMPLE = """{"role":"user","content":"Hello"}
{"role":"assistant","content":"Hi there!"}
{"role":"assistant","content":" How can I help?","tool_calls":[{"name":"read_file","arguments":{"path":"test.py"}}]}
{"role":"tool","content":"file content here","tool_call_id":"call_1"}"""


@pytest.fixture
def claude_stream_json() -> str:
    """Sample Claude CLI stream-json output."""
    return CLAUDE_STREAM_JSON_SAMPLE


@pytest.fixture
def claude_tool_use_json() -> str:
    """Sample Claude CLI output with tool use."""
    return CLAUDE_TOOL_USE_SAMPLE


@pytest.fixture
def claude_thinking_json() -> str:
    """Sample Claude CLI output with thinking."""
    return CLAUDE_THINKING_SAMPLE


@pytest.fixture
def claude_error_json() -> str:
    """Sample Claude CLI error output."""
    return CLAUDE_ERROR_SAMPLE


@pytest.fixture
def gemini_stream_json() -> str:
    """Sample Gemini CLI stream-json output."""
    return GEMINI_STREAM_JSON_SAMPLE


@pytest.fixture
def grok_jsonl() -> str:
    """Sample Grok CLI JSONL output."""
    return GROK_JSONL_SAMPLE
