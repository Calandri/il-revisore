/**
 * ChatAPIClient - Main API client for TurboWrap Chat
 */

import type {
  Session,
  Message,
  Agent,
  ContextInfo,
  UsageInfo,
  CreateSessionOptions,
  UpdateSessionOptions,
  SessionAPIResponse,
  MessageAPIResponse,
} from '../types';
import { transformSession, transformMessage } from '../types';
import type {
  ChatClientConfig,
  StreamMessageOptions,
  GetSessionsOptions,
  GetMessagesOptions,
} from './types';
import { ChatAPIError } from './types';
import { parseSSEStream } from './sse-parser';

/**
 * API client for TurboWrap Chat backend
 */
export class ChatAPIClient {
  private config: Required<Pick<ChatClientConfig, 'baseUrl' | 'timeout'>> & ChatClientConfig;

  constructor(config: ChatClientConfig) {
    this.config = {
      timeout: 120000,
      ...config,
      baseUrl: config.baseUrl.replace(/\/$/, ''),
    };
  }

  // ============================================================================
  // Private helpers
  // ============================================================================

  private async getHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...this.config.headers,
    };

    if (this.config.getAuthToken) {
      try {
        const token = await this.config.getAuthToken();
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }
      } catch (error) {
        // Log the error but continue without auth header
        // This allows requests to proceed even if token retrieval fails
        console.error('Failed to get auth token:', error);
        this.config.onError?.(
          error instanceof Error
            ? error
            : new Error('Failed to get auth token')
        );
      }
    }

    return headers;
  }

  private async handleError(response: Response): Promise<ChatAPIError> {
    if (response.status === 401) {
      this.config.onUnauthorized?.();
    }

    try {
      const data = await response.json();
      const error = new ChatAPIError(
        data.detail || data.message || `HTTP ${response.status}`,
        response.status,
        data.error_type
      );
      this.config.onError?.(error);
      return error;
    } catch {
      const error = new ChatAPIError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status
      );
      this.config.onError?.(error);
      return error;
    }
  }

  private async fetch<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.config.baseUrl}${endpoint}`;
    const headers = await this.getHeaders();

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeout);

    try {
      const response = await fetch(url, {
        ...options,
        headers: { ...headers, ...options.headers },
        signal: options.signal || controller.signal,
      });

      if (!response.ok) {
        throw await this.handleError(response);
      }

      return response.json();
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ============================================================================
  // Session Management
  // ============================================================================

  /**
   * Get all chat sessions
   */
  async getSessions(options?: GetSessionsOptions): Promise<Session[]> {
    const params = new URLSearchParams();
    if (options?.repositoryId) params.set('repository_id', options.repositoryId);
    if (options?.cliType) params.set('cli_type', options.cliType);
    if (options?.limit) params.set('limit', options.limit.toString());

    const query = params.toString();
    const endpoint = `/api/cli-chat/sessions${query ? `?${query}` : ''}`;

    const data = await this.fetch<SessionAPIResponse[]>(endpoint);
    return data.map(transformSession);
  }

  /**
   * Create a new chat session
   */
  async createSession(options: CreateSessionOptions): Promise<Session> {
    const data = await this.fetch<SessionAPIResponse>('/api/cli-chat/sessions', {
      method: 'POST',
      body: JSON.stringify({
        cli_type: options.cliType,
        repository_id: options.repositoryId,
        display_name: options.displayName,
        icon: options.icon,
        color: options.color,
        mockup_project_id: options.mockupProjectId,
        mockup_id: options.mockupId,
      }),
    });

    return transformSession(data);
  }

  /**
   * Get a single session by ID
   */
  async getSession(sessionId: string): Promise<Session> {
    const data = await this.fetch<SessionAPIResponse>(
      `/api/cli-chat/sessions/${sessionId}`
    );
    return transformSession(data);
  }

  /**
   * Update session settings
   */
  async updateSession(
    sessionId: string,
    options: UpdateSessionOptions
  ): Promise<Session> {
    const data = await this.fetch<SessionAPIResponse>(
      `/api/cli-chat/sessions/${sessionId}`,
      {
        method: 'PUT',
        body: JSON.stringify({
          display_name: options.displayName,
          icon: options.icon,
          color: options.color,
          position: options.position,
          model: options.model,
          agent_name: options.agentName,
          thinking_enabled: options.thinkingEnabled,
          thinking_budget: options.thinkingBudget,
          reasoning_enabled: options.reasoningEnabled,
          mcp_servers: options.mcpServers,
          mockup_project_id: options.mockupProjectId,
          mockup_id: options.mockupId,
        }),
      }
    );
    return transformSession(data);
  }

  /**
   * Delete a session (soft delete)
   */
  async deleteSession(sessionId: string): Promise<void> {
    await this.fetch(`/api/cli-chat/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Start the CLI process for a session
   */
  async startSession(
    sessionId: string
  ): Promise<{ status: string; claudeSessionId?: string }> {
    return this.fetch(`/api/cli-chat/sessions/${sessionId}/start`, {
      method: 'POST',
    });
  }

  /**
   * Stop the CLI process for a session
   */
  async stopSession(sessionId: string): Promise<{ status: string }> {
    return this.fetch(`/api/cli-chat/sessions/${sessionId}/stop`, {
      method: 'POST',
    });
  }

  /**
   * Fork a session (duplicate with messages)
   */
  async forkSession(sessionId: string): Promise<Session> {
    const data = await this.fetch<SessionAPIResponse>(
      `/api/cli-chat/sessions/${sessionId}/fork`,
      { method: 'POST' }
    );
    return transformSession(data);
  }

  /**
   * Get available branches for session's repository
   */
  async getBranches(sessionId: string): Promise<string[]> {
    return this.fetch(`/api/cli-chat/sessions/${sessionId}/branches`);
  }

  /**
   * Change the active branch for a session
   */
  async changeBranch(sessionId: string, branch: string): Promise<Session> {
    const data = await this.fetch<SessionAPIResponse>(
      `/api/cli-chat/sessions/${sessionId}/branch`,
      {
        method: 'POST',
        body: JSON.stringify({ branch }),
      }
    );
    return transformSession(data);
  }

  // ============================================================================
  // Messages
  // ============================================================================

  /**
   * Get messages for a session
   */
  async getMessages(
    sessionId: string,
    options?: GetMessagesOptions
  ): Promise<Message[]> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', options.limit.toString());
    if (options?.includeThinking) params.set('include_thinking', 'true');

    const query = params.toString();
    const endpoint = `/api/cli-chat/sessions/${sessionId}/messages${query ? `?${query}` : ''}`;

    const data = await this.fetch<MessageAPIResponse[]>(endpoint);
    return data.map(transformMessage);
  }

  /**
   * Send a message and stream the response via SSE
   */
  async streamMessage(
    sessionId: string,
    content: string,
    options: StreamMessageOptions = {}
  ): Promise<void> {
    const headers = await this.getHeaders();

    const response = await fetch(
      `${this.config.baseUrl}/api/cli-chat/sessions/${sessionId}/message`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          content,
          model_override: options.modelOverride,
        }),
        signal: options.signal,
      }
    );

    if (!response.ok) {
      const error = await this.handleError(response);
      options.onError?.(error);
      return;
    }

    await parseSSEStream(response, options, options.signal);
  }

  // ============================================================================
  // Context & Usage
  // ============================================================================

  /**
   * Get context info for a session (tokens, categories, etc.)
   */
  async getContextInfo(sessionId: string): Promise<ContextInfo> {
    const data = await this.fetch<Record<string, unknown>>(
      `/api/cli-chat/sessions/${sessionId}/context`
    );

    return {
      model: data.model as string | undefined,
      tokens: {
        used: (data.tokens_in as number) || 0,
        limit: 200000, // Default for Claude
        percentage: ((data.tokens_in as number) || 0) / 200000 * 100,
      },
      categories: (data.categories as Array<{ name: string; tokens: number }>) || [],
      mcpTools: (data.mcpTools as Array<{ name: string; server?: string; tokens?: number }>) || [],
      agents: (data.agents as Array<{ name: string; source?: string; tokens?: number }>) || [],
    };
  }

  /**
   * Get usage info for a session (version, MCP servers, etc.)
   */
  async getUsageInfo(sessionId: string): Promise<UsageInfo> {
    const data = await this.fetch<Record<string, unknown>>(
      `/api/cli-chat/sessions/${sessionId}/usage`
    );

    return {
      version: data.version as string | undefined,
      sessionId: data.session_id as string | undefined,
      cwd: data.cwd as string | undefined,
      loginMethod: data.login_method as string | undefined,
      organization: data.organization as string | undefined,
      email: data.email as string | undefined,
      model: data.model as string | undefined,
      modelId: data.model_id as string | undefined,
      ide: data.ide as string | undefined,
      ideVersion: data.ide_version as string | undefined,
      mcpServers: (data.mcp_servers as Array<{ name: string; connected: boolean }>) || [],
      memory: data.memory as string | undefined,
      settingSources: data.setting_sources as string | undefined,
    };
  }

  // ============================================================================
  // Agents
  // ============================================================================

  /**
   * Get list of available agents
   */
  async getAgents(): Promise<Agent[]> {
    const data = await this.fetch<{ agents: Agent[]; total: number }>(
      '/api/cli-chat/agents'
    );
    return data.agents;
  }

  /**
   * Get a single agent by name
   */
  async getAgent(agentName: string): Promise<Agent> {
    return this.fetch(`/api/cli-chat/agents/${agentName}`);
  }

  // ============================================================================
  // Slash Commands
  // ============================================================================

  /**
   * Get slash command prompt by name
   */
  async getSlashCommand(
    commandName: string
  ): Promise<{ name: string; prompt: string; path: string }> {
    return this.fetch(`/api/cli-chat/commands/${commandName}`);
  }

  /**
   * List available slash commands
   */
  async getSlashCommands(): Promise<{ commands: string[]; total: number }> {
    return this.fetch('/api/cli-chat/commands');
  }

  // ============================================================================
  // Repositories
  // ============================================================================

  /**
   * Get list of repositories
   */
  async getRepositories(): Promise<Array<{
    id: string;
    name: string;
    path: string;
    default_branch: string;
    url?: string;
  }>> {
    return this.fetch('/api/git/repositories');
  }
}
