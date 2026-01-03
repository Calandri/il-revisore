import type {
  WidgetConfig,
  AnalyzeRequest,
  AnalyzeResult,
  FinalizeRequest,
  IssueCreatedResult,
  Question,
  ChatContext,
  ChatSessionResponse,
  ChatActionData,
} from './types';

export class IssueAPIClient {
  private baseUrl: string;
  private apiKey: string;
  private teamId: string;

  constructor(config: WidgetConfig) {
    this.baseUrl = config.apiUrl.replace(/\/$/, '');
    this.apiKey = config.apiKey;
    this.teamId = config.teamId;
  }

  async analyzeIssue(
    data: AnalyzeRequest,
    onProgress: (msg: string) => void,
    onComplete: (result: AnalyzeResult) => void,
    onError: (error: string) => void
  ): Promise<void> {
    const formData = new FormData();
    formData.append('title', data.title);
    formData.append('description', data.description);
    formData.append('issue_type', data.issueType);

    data.screenshots.forEach((blob, index) => {
      const timestamp = Date.now();
      formData.append('screenshots', blob, `screenshot-${index}-${timestamp}.png`);
    });

    if (data.figmaLink) formData.append('figma_link', data.figmaLink);
    if (data.websiteLink) formData.append('website_link', data.websiteLink);
    if (data.selectedElement) {
      formData.append('selected_element', JSON.stringify(data.selectedElement));
    }

    try {
      const response = await fetch(`${this.baseUrl}/api/linear/create/analyze`, {
        method: 'POST',
        headers: {
          'X-Widget-Key': this.apiKey,
        },
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      await this.parseSSEStream(response, onProgress, (data) => {
        if (data.questions && data.gemini_insights !== undefined) {
          onComplete({
            questions: data.questions as Question[],
            geminiInsights: data.gemini_insights as string,
            tempSessionId: data.temp_session_id as string,
          });
        }
      }, onError);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error');
    }
  }

  async finalizeIssue(
    data: FinalizeRequest,
    onProgress: (msg: string) => void,
    onComplete: (result: IssueCreatedResult) => void,
    onError: (error: string) => void
  ): Promise<void> {
    try {
      const response = await fetch(`${this.baseUrl}/api/linear/create/finalize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Widget-Key': this.apiKey,
        },
        body: JSON.stringify({
          title: data.title,
          description: data.description,
          issue_type: data.issueType,
          user_answers: data.userAnswers,
          gemini_insights: data.geminiInsights,
          team_id: data.teamId || this.teamId,
          temp_session_id: data.tempSessionId,
          figma_link: data.figmaLink,
          website_link: data.websiteLink,
          selected_element: data.selectedElement,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      await this.parseSSEStream(response, onProgress, (data) => {
        if (data.identifier && data.url && data.id) {
          onComplete({
            id: data.id as string,
            identifier: data.identifier as string,
            url: data.url as string,
          });
        }
      }, onError);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error');
    }
  }

  private async parseSSEStream(
    response: Response,
    onProgress: (msg: string) => void,
    onData: (data: Record<string, unknown>) => void,
    onError: (error: string) => void
  ): Promise<void> {
    const reader = response.body?.getReader();
    if (!reader) {
      onError('Response body is not readable');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const eventBlock of events) {
          if (!eventBlock.trim()) continue;

          const lines = eventBlock.split('\n');
          let currentEvent = '';
          let currentData = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataLine = line.slice(6);
              currentData += currentData ? '\n' + dataLine : dataLine;
            }
          }

          if (currentData) {
            try {
              const data = JSON.parse(currentData) as Record<string, unknown>;

              if (currentEvent === 'error' || data.error) {
                onError(String(data.error || data.message || 'Unknown error'));
                return;
              }

              if (data.message && (currentEvent === 'progress' || currentEvent === 'log')) {
                onProgress(String(data.message));
              }

              if (currentEvent === 'complete' || data.questions || data.identifier) {
                onData(data);
              }
            } catch (parseError) {
              console.warn('Failed to parse SSE data:', parseError);
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  async createChatSession(context?: ChatContext): Promise<ChatSessionResponse> {
    const response = await fetch(`${this.baseUrl}/api/widget-chat/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Widget-Key': this.apiKey,
      },
      body: JSON.stringify({ context }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
  }

  async sendChatMessage(
    sessionId: string,
    message: string,
    context: ChatContext | undefined,
    onChunk: (content: string) => void,
    onAction: (action: ChatActionData) => void,
    onComplete: () => void,
    onError: (error: string) => void
  ): Promise<void> {
    try {
      const response = await fetch(
        `${this.baseUrl}/api/widget-chat/sessions/${sessionId}/message`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Widget-Key': this.apiKey,
          },
          body: JSON.stringify({
            message,
            session_id: sessionId,
            context,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      await this.parseChatSSEStream(response, onChunk, onAction, onComplete, onError);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error');
    }
  }

  async deleteChatSession(sessionId: string): Promise<void> {
    await fetch(`${this.baseUrl}/api/widget-chat/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'X-Widget-Key': this.apiKey,
      },
    });
  }

  private async parseChatSSEStream(
    response: Response,
    onChunk: (content: string) => void,
    onAction: (action: ChatActionData) => void,
    onComplete: () => void,
    onError: (error: string) => void
  ): Promise<void> {
    const reader = response.body?.getReader();
    if (!reader) {
      onError('Response body is not readable');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr) as Record<string, unknown>;

              if (currentEvent === 'error' || data.error) {
                onError(String(data.error || 'Unknown error'));
                return;
              }

              if (currentEvent === 'chunk' && data.content) {
                onChunk(String(data.content));
              }

              if (currentEvent === 'action' && data.type && data.data) {
                onAction(data as unknown as ChatActionData);
              }

              if (currentEvent === 'done') {
                onComplete();
              }
            } catch (parseError) {
              console.warn('Failed to parse chat SSE data:', parseError);
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}
