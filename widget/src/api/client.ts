import type {
  WidgetConfig,
  AnalyzeRequest,
  AnalyzeResult,
  FinalizeRequest,
  IssueCreatedResult,
  Question,
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

    data.screenshots.forEach((blob, index) => {
      formData.append('screenshots', blob, `screenshot-${index}-${Date.now()}.png`);
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
                onError(String(data.error || data.message || 'Unknown error'));
                return;
              }

              if (data.message && (currentEvent === 'progress' || currentEvent === 'log')) {
                onProgress(String(data.message));
              }

              if (currentEvent === 'complete' || data.questions || data.identifier) {
                onData(data);
              }
            } catch {
              // Incomplete JSON chunk, continue
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}
