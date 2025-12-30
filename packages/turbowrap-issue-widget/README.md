# @turbowrap/issue-widget

Embeddable chatbot widget for collecting issues via TurboWrap.

## Installation

### Script Tag (CDN)

```html
<script>
  window.IssueWidgetConfig = {
    apiUrl: 'https://your-api.turbowrap.io',
    apiKey: 'your_api_key',
    teamId: 'your-linear-team-uuid'
  };
</script>
<script src="https://cdn.jsdelivr.net/npm/@turbowrap/issue-widget@latest/dist/issue-widget.min.js" async></script>
```

### npm

```bash
npm install @turbowrap/issue-widget
```

```javascript
import { IssueWidget } from '@turbowrap/issue-widget';

const widget = new IssueWidget({
  apiUrl: 'https://your-api.turbowrap.io',
  apiKey: 'your_api_key',
  teamId: 'your-linear-team-uuid'
});
```

## Configuration

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `apiUrl` | string | Yes | - | TurboWrap API URL |
| `apiKey` | string | Yes | - | Widget API key |
| `teamId` | string | Yes | - | Linear team UUID |
| `position` | string | No | `'bottom-right'` | Button position: `'bottom-right'` or `'bottom-left'` |
| `theme` | string | No | `'auto'` | Theme: `'light'`, `'dark'`, or `'auto'` |
| `buttonText` | string | No | `'Report Issue'` | Floating button text |
| `accentColor` | string | No | `'#6366f1'` | Primary accent color (hex) |
| `autoScreenshot` | boolean | No | `false` | Auto-capture on widget open |
| `screenshotMethod` | string | No | `'auto'` | `'display-media'`, `'html2canvas'`, or `'auto'` |

## Callbacks

```javascript
window.IssueWidgetConfig = {
  // ... required options ...

  onOpen: () => {
    console.log('Widget opened');
  },

  onClose: () => {
    console.log('Widget closed');
  },

  onIssueCreated: (issue) => {
    console.log('Issue created:', issue);
    // issue: { id, identifier, url }
  },

  onError: (error) => {
    console.error('Widget error:', error);
  }
};
```

## Features

- **Screen Capture**: Uses `getDisplayMedia` API with `html2canvas` fallback
- **AI Analysis**: Gemini Vision analyzes screenshots, Claude generates clarifying questions
- **Linear Integration**: Creates issues directly in your Linear workspace
- **Shadow DOM**: Styles are isolated, no conflicts with host site CSS
- **Responsive**: Works on mobile and desktop
- **Dark Mode**: Automatic theme detection

## Development

```bash
# Install dependencies
npm install

# Development server
npm run dev

# Build for production
npm run build

# Type check
npm run typecheck
```

## Backend Configuration

The widget requires CORS enabled on your TurboWrap backend. Set the environment variable:

```bash
TURBOWRAP_SERVER_CORS_ORIGINS=["https://your-customer-site.com"]
```

Or for development (allow all):

```bash
TURBOWRAP_SERVER_CORS_ORIGINS=["*"]
```

## License

MIT
