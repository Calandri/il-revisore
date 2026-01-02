# @turbowrap/chat

React chat widget for Claude/Gemini CLI with SSE streaming.

## Installation

```bash
npm install @turbowrap/chat
```

## Quick Start

```tsx
import { ChatWidget } from '@turbowrap/chat';

function App() {
  return (
    <ChatWidget
      config={{
        apiUrl: 'https://your-api.turbowrap.io',
        getAuthToken: () => localStorage.getItem('token') || '',
        defaultCliType: 'claude',
      }}
    />
  );
}
```

## Features

- **Multi-session chat** - Multiple concurrent chat sessions
- **Dual chat mode** - Side-by-side sessions
- **SSE streaming** - Real-time streaming with tool/agent events
- **Agent autocomplete** - @mention for agents
- **Slash commands** - /commit, /pr, /review, etc.
- **Model selector** - Claude (Opus/Sonnet) and Gemini (Pro/Flash)
- **Dark mode** - Auto, light, or dark theme

## API

### ChatWidget

Main component that renders the chat interface.

```tsx
<ChatWidget
  config={{
    // Required
    apiUrl: string;

    // Authentication
    getAuthToken?: () => string | Promise<string>;

    // Defaults
    defaultCliType?: 'claude' | 'gemini';
    defaultMode?: 'third' | 'full' | 'page';
    theme?: 'light' | 'dark' | 'auto';

    // Feature toggles
    enableDualChat?: boolean;
    enableAgentAutocomplete?: boolean;
    enableSlashCommands?: boolean;

    // Callbacks
    onSessionCreate?: (session: Session) => void;
    onMessageSend?: (sessionId: string, content: string) => void;
    onNavigate?: (path: string) => void;
    onHighlight?: (selector: string) => void;
    onError?: (error: Error) => void;
  }}
/>
```

### Hooks

#### useChat

Main hook for chat functionality.

```tsx
const {
  messages,
  isStreaming,
  streamContent,
  activeTools,
  activeAgents,
  error,
  sendMessage,
  stopStream,
  queueMessage,
} = useChat();
```

#### useSessions

Hook for session management.

```tsx
const {
  sessions,
  activeSession,
  createSession,
  selectSession,
  deleteSession,
  forkSession,
} = useSessions();
```

#### useAgents

Hook for agent autocomplete.

```tsx
const {
  agents,
  filteredAgents,
  query,
  setQuery,
  getSelectedAgent,
} = useAgents();
```

#### useDualChat

Hook for dual chat mode.

```tsx
const {
  isDualChatEnabled,
  leftSession,
  rightSession,
  toggleDualChat,
  swapSessions,
} = useDualChat();
```

### Direct API Client Usage

For advanced use cases, you can use the API client directly:

```tsx
import { ChatAPIClient } from '@turbowrap/chat';

const client = new ChatAPIClient({
  baseUrl: 'https://your-api.turbowrap.io',
  getAuthToken: () => localStorage.getItem('token'),
});

// Get sessions
const sessions = await client.getSessions();

// Stream a message
await client.streamMessage(sessionId, 'Hello', {
  onChunk: (content) => console.log(content),
  onDone: (messageId) => console.log('Done:', messageId),
});
```

## Development

```bash
# Install dependencies
npm install

# Run type check
npm run typecheck

# Build
npm run build

# Dev server
npm run dev
```

## License

MIT
