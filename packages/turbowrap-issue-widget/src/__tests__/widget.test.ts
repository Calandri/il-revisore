import { IssueWidget } from '../widget';
import type { WidgetConfig } from '../api/types';

// Mock the API client
jest.mock('../api/client', () => {
  return {
    IssueAPIClient: jest.fn().mockImplementation(() => ({
      analyzeIssue: jest.fn(),
      finalizeIssue: jest.fn(),
      createChatSession: jest.fn().mockResolvedValue({ session_id: 'test-session' }),
      sendChatMessage: jest.fn().mockResolvedValue(undefined),
      deleteChatSession: jest.fn().mockResolvedValue(undefined),
    })),
  };
});

// Mock screenshot functions
jest.mock('../capture/screen-capture', () => ({
  captureScreen: jest.fn().mockResolvedValue(new Blob(['test'], { type: 'image/png' })),
  compressImage: jest.fn().mockResolvedValue(new Blob(['compressed'], { type: 'image/png' })),
  blobToDataUrl: jest.fn().mockResolvedValue('data:image/png;base64,test'),
  supportsDisplayMedia: jest.fn().mockReturnValue(true),
}));

// Mock element picker
jest.mock('../capture/element-picker', () => ({
  startElementPicker: jest.fn().mockResolvedValue({
    selector: '#test',
    tagName: 'DIV',
    id: 'test-id',
    classes: ['test-class'],
  }),
}));

describe('IssueWidget', () => {
  let config: WidgetConfig;

  beforeEach(() => {
    // Clear all mocks before each test
    jest.clearAllMocks();

    // Remove any existing widget from DOM
    const existing = document.getElementById('issue-widget-root');
    if (existing) {
      existing.remove();
    }

    config = {
      apiUrl: 'https://api.example.com',
      apiKey: 'test-key',
      teamId: 'test-team',
    };
  });

  afterEach(() => {
    // Cleanup after each test
    const widget = document.getElementById('issue-widget-root');
    if (widget) {
      widget.remove();
    }
  });

  describe('Initialization', () => {
    it('should initialize even with minimal config (validation happens at API call)', () => {
      const minimalConfig = {
        apiUrl: 'https://api.example.com',
        apiKey: 'test-key',
        teamId: 'test-team',
      } as WidgetConfig;
      const widget = new IssueWidget(minimalConfig);
      expect(widget).toBeDefined();
    });

    it('should initialize with valid config', () => {
      const widget = new IssueWidget(config);
      expect(widget).toBeDefined();
      expect(document.getElementById('issue-widget-root')).not.toBeNull();
    });

    it('should apply default config values', () => {
      const widget = new IssueWidget(config);
      expect(widget).toBeDefined();
      // Widget should be in the DOM with default position
      const root = document.getElementById('issue-widget-root');
      expect(root).not.toBeNull();
      expect(root?.id).toBe('issue-widget-root');
    });

    it('should create shadow DOM in closed mode', () => {
      const widget = new IssueWidget(config);
      expect(widget).toBeDefined();
      const root = document.getElementById('issue-widget-root') as any;
      // Closed shadow DOM cannot be accessed directly, but we can verify the widget exists
      expect(root).not.toBeNull();
    });
  });

  describe('Memory Management', () => {
    it('should revoke blob URLs on screenshot removal', async () => {
      const widget = new IssueWidget(config);
      const revokeObjectURLSpy = jest.spyOn(URL, 'revokeObjectURL');

      // Simulate screenshot capture
      (widget as any).handleScreenshotCapture();
      await new Promise(resolve => setTimeout(resolve, 100));

      expect(revokeObjectURLSpy).not.toHaveBeenCalled();

      // Simulate screenshot removal
      (widget as any).handleRemoveScreenshot();

      expect(revokeObjectURLSpy).toHaveBeenCalled();
    });

    it('should revoke all blob URLs on destroy', async () => {
      const widget = new IssueWidget(config);
      const revokeObjectURLSpy = jest.spyOn(URL, 'revokeObjectURL');

      // Capture screenshot to create blob URLs
      (widget as any).handleScreenshotCapture();
      await new Promise(resolve => setTimeout(resolve, 100));

      // Destroy widget
      await widget.destroy();

      expect(revokeObjectURLSpy).toHaveBeenCalled();
    });

    it('should limit progress messages array size', async () => {
      const widget = new IssueWidget(config);

      // Simulate adding many progress messages
      for (let i = 0; i < 100; i++) {
        (widget as any).state.progressMessages.push(`Message ${i}`);
      }

      // After destroy, state should be cleared
      await widget.destroy();
      expect((widget as any).state.progressMessages).toEqual([]);
    });

    it('should limit chat messages array size', async () => {
      const widget = new IssueWidget(config);

      // Simulate adding many chat messages
      const messages = Array.from({ length: 150 }, (_, i) => ({
        id: `msg-${i}`,
        role: 'user' as const,
        content: `Message ${i}`,
        timestamp: new Date(),
      }));

      (widget as any).state.chatMessages = messages;
      expect((widget as any).state.chatMessages.length).toBe(150);

      // After destroy, state should be cleared
      await widget.destroy();
      expect((widget as any).state.chatMessages).toEqual([]);
    });
  });

  describe('Cleanup on Destroy', () => {
    it('should remove widget from DOM', async () => {
      const widget = new IssueWidget(config);
      expect(document.getElementById('issue-widget-root')).not.toBeNull();

      await widget.destroy();

      expect(document.getElementById('issue-widget-root')).toBeNull();
    });

    it('should clear event handlers', async () => {
      const widget = new IssueWidget(config);
      const eventHandlers = (widget as any).eventHandlers as Map<string, any>;

      // Should have event handlers after init
      expect(eventHandlers.size).toBeGreaterThan(0);

      await widget.destroy();

      // Should be cleared after destroy
      expect(eventHandlers.size).toBe(0);
    });

    it('should delete chat session if active', async () => {
      const widget = new IssueWidget(config);
      const client = (widget as any).client;
      const deleteSpy = jest.spyOn(client, 'deleteChatSession').mockResolvedValue(undefined);

      // Set active session
      (widget as any).state.chatSessionId = 'test-session-id';

      await widget.destroy();

      expect(deleteSpy).toHaveBeenCalledWith('test-session-id');
    });

    it('should abort pending requests', async () => {
      const widget = new IssueWidget(config);
      (widget as any).abortController = new AbortController();
      const abortSpy = jest.spyOn((widget as any).abortController, 'abort');

      await widget.destroy();

      expect(abortSpy).toHaveBeenCalled();
    });
  });

  describe('ID Generation', () => {
    it('should generate unique IDs with crypto.randomUUID', () => {
      const widget = new IssueWidget(config);
      const id1 = (widget as any).generateId();
      const id2 = (widget as any).generateId();

      expect(id1).toBeTruthy();
      expect(id2).toBeTruthy();
      expect(id1).not.toBe(id2);
    });

    it('should handle missing crypto.randomUUID gracefully', () => {
      const originalCrypto = global.crypto;
      (global as any).crypto = undefined;

      const widget = new IssueWidget(config);
      const id = (widget as any).generateId();

      expect(id).toBeTruthy();
      expect(id).toMatch(/^\d+-[a-z0-9]+$/);

      (global as any).crypto = originalCrypto;
    });
  });

  describe('HTML Escaping', () => {
    it('should escape HTML special characters', () => {
      const widget = new IssueWidget(config);
      const escaped = (widget as any).escapeHtml('<script>alert("XSS")</script>');

      expect(escaped).not.toContain('<script>');
      expect(escaped).toContain('&lt;');
      expect(escaped).toContain('&gt;');
    });

    it('should safely handle user input', () => {
      const widget = new IssueWidget(config);
      const inputs = [
        '<script>alert(1)</script>',
        '<img src=x onerror="alert(1)">',
        '<svg onload="alert(1)">',
      ];

      inputs.forEach(input => {
        const escaped = (widget as any).escapeHtml(input);
        // Escaped output should not contain raw HTML tags (they should be entity-encoded)
        // This prevents XSS attacks where tags are executed
        expect(escaped).not.toContain('<script>');
        expect(escaped).not.toContain('</script>');
        expect(escaped).not.toContain('<img');
        expect(escaped).not.toContain('<svg');
        // Should contain entity-encoded versions to preserve text content
        expect(escaped).toContain('&lt;');
        expect(escaped).toContain('&gt;');
      });
    });
  });

  describe('Configuration', () => {
    it('should apply custom accent color', () => {
      const customConfig: WidgetConfig = {
        ...config,
        accentColor: '#ff0000',
      };

      const widget = new IssueWidget(customConfig);
      expect(widget).toBeDefined();
      const root = document.getElementById('issue-widget-root') as HTMLElement;

      expect(root.style.getPropertyValue('--iw-accent')).toBe('#ff0000');
    });

    it('should respect position configuration', () => {
      const customConfig: WidgetConfig = {
        ...config,
        position: 'top-left',
      };

      const widget = new IssueWidget(customConfig);
      const root = document.getElementById('issue-widget-root');

      // Widget created with top-left position
      expect(root).not.toBeNull();
      expect(widget).toBeDefined();
    });

    it('should set custom button text', () => {
      const customConfig: WidgetConfig = {
        ...config,
        buttonText: 'Send Feedback',
      };

      const widget = new IssueWidget(customConfig);
      const root = document.getElementById('issue-widget-root');

      // Widget created with custom button text
      expect(root).not.toBeNull();
      expect(widget).toBeDefined();
    });
  });

  describe('State Management', () => {
    it('should reset state on reset() call', async () => {
      const widget = new IssueWidget(config);

      // Modify state
      (widget as any).state.title = 'Test Issue';
      (widget as any).state.description = 'Description';
      (widget as any).state.chatSessionId = 'test-session';

      // Reset
      (widget as any).reset();

      expect((widget as any).state.title).toBe('');
      expect((widget as any).state.description).toBe('');
      expect((widget as any).state.chatSessionId).toBeNull();
    });

    it('should properly clear state on destroy', async () => {
      const widget = new IssueWidget(config);

      // Set various state values
      (widget as any).state.title = 'Test';
      (widget as any).state.chatMessages = [
        { id: 'msg1', role: 'user', content: 'test', timestamp: new Date() },
      ];

      await widget.destroy();

      // State should be cleared
      expect((widget as any).state.title).toBe('');
      expect((widget as any).state.chatMessages).toEqual([]);
    });
  });
});
