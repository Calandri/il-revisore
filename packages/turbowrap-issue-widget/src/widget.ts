import type {
  WidgetConfig,
  AnalyzeResult,
  IssueCreatedResult,
  Question,
  ElementInfo,
  IssueType,
  WidgetMode,
  ChatMessage,
  ChatContext,
  ChatActionData,
} from './api/types';
import { IssueAPIClient } from './api/client';
import { captureScreenWithSelection, compressImage, blobToDataUrl } from './capture/screen-capture';
import { startElementPicker } from './capture/element-picker';
import { WIDGET_STYLES } from './ui/styles';
import { ICONS } from './ui/icons';

const WIDGET_VERSION = '1.0.22';

type Step = 'details' | 'questions' | 'creating' | 'success' | 'error';

interface WidgetState {
  isOpen: boolean;
  step: Step;
  issueType: IssueType;
  title: string;
  description: string;
  screenshots: Blob[];
  screenshotPreviews: string[];
  selectedElement: ElementInfo | null;
  questions: Question[];
  answers: Record<number, string>;
  geminiInsights: string;
  tempSessionId: string;
  progressMessages: string[];
  createdIssue: IssueCreatedResult | null;
  error: string | null;
  isLoading: boolean;
  isCapturingScreenshot: boolean;
  // Repository context
  repositoryId: string | null;
  // Chat mode
  mode: WidgetMode;
  chatSessionId: string | null;
  chatMessages: ChatMessage[];
  chatInput: string;
  chatIsStreaming: boolean;
  chatStreamingContent: string;
}

// Memory limits for arrays
const MAX_CHAT_MESSAGES = 100;
const MAX_PROGRESS_MESSAGES = 50;

export class IssueWidget {
  private config: WidgetConfig;
  private client: IssueAPIClient;
  private container: HTMLElement;
  private shadow: ShadowRoot;
  private state: WidgetState;

  // Memory management
  private blobUrls: string[] = [];
  private eventHandlers: Map<string, EventListener> = new Map();
  private abortController: AbortController | null = null;

  constructor(config: WidgetConfig) {
    this.config = {
      position: 'bottom-right',
      theme: 'auto',
      buttonText: 'Report Issue',
      screenshotMethod: 'auto',
      ...config,
    };

    this.client = new IssueAPIClient(this.config);

    this.state = {
      isOpen: false,
      step: 'details',
      issueType: 'bug',
      title: '',
      description: '',
      screenshots: [],
      screenshotPreviews: [],
      selectedElement: null,
      questions: [],
      answers: {},
      geminiInsights: '',
      tempSessionId: '',
      progressMessages: [],
      createdIssue: null,
      error: null,
      isLoading: false,
      isCapturingScreenshot: false,
      // Repository context
      repositoryId: this.config.repositoryId || null,
      // Chat mode
      mode: 'form',
      chatSessionId: null,
      chatMessages: [],
      chatInput: '',
      chatIsStreaming: false,
      chatStreamingContent: '',
    };

    this.container = document.createElement('div');
    this.container.id = 'issue-widget-root';
    this.shadow = this.container.attachShadow({ mode: 'closed' });

    this.injectStyles();
    this.render();
    document.body.appendChild(this.container);
  }

  private injectStyles(): void {
    const style = document.createElement('style');
    style.textContent = WIDGET_STYLES;
    this.shadow.appendChild(style);

    // Apply theme
    if (this.config.theme === 'dark') {
      this.shadow.host.classList.add('dark');
    } else if (this.config.theme === 'auto') {
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        this.shadow.host.classList.add('dark');
      }
    }

    // Apply accent color
    if (this.config.accentColor) {
      (this.shadow.host as HTMLElement).style.setProperty(
        '--iw-accent',
        this.config.accentColor
      );
    }
  }

  private render(): void {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = this.getHTML();
    this.shadow.appendChild(wrapper);
    this.attachEventListeners();
  }
  private addChatMessage(message: ChatMessage): void {
    this.state.chatMessages.push(message);
    if (this.state.chatMessages.length > MAX_CHAT_MESSAGES) {
      this.state.chatMessages = this.state.chatMessages.slice(-MAX_CHAT_MESSAGES);
    }
  }

  private addProgressMessage(message: string): void {
    this.state.progressMessages.push(message);
    if (this.state.progressMessages.length > MAX_PROGRESS_MESSAGES) {
      this.state.progressMessages.shift();
    }
  }

  private getHTML(): string {
    const position = this.config.position || 'bottom-right';
    const { step, isOpen, mode } = this.state;

    return `
      <button class="iw-trigger ${position}" id="iw-trigger" aria-label="${this.config.buttonText}">
        ${ICONS.bug}
        <span>${this.config.buttonText}</span>
      </button>

      <div class="iw-modal-overlay ${isOpen ? 'open' : ''}" id="iw-overlay"></div>

      <div class="iw-modal ${position} ${isOpen ? 'open' : ''}" id="iw-modal"
           role="dialog" aria-modal="true" aria-labelledby="iw-modal-title">
        <div class="iw-header">
          <div class="iw-header-title">
            <h2 id="iw-modal-title">${mode === 'chat' ? 'Chat' : 'Report an Issue'}</h2>
            <span class="iw-version">v${WIDGET_VERSION}</span>
          </div>
          <button class="iw-close" id="iw-close" aria-label="Close dialog">&times;</button>
        </div>

        <!-- Mode Selector -->
        <div class="iw-mode-selector" role="tablist">
          <button class="iw-mode-btn ${mode === 'form' ? 'active' : ''}" data-mode="form"
                  role="tab" aria-selected="${mode === 'form'}" aria-label="Report Issue form mode">
            ${ICONS.form}
            <span>Report Issue</span>
          </button>
          <button class="iw-mode-btn ${mode === 'chat' ? 'active' : ''}" data-mode="chat"
                  role="tab" aria-selected="${mode === 'chat'}" aria-label="Chat mode">
            ${ICONS.chat}
            <span>Chat</span>
          </button>
        </div>

        ${mode === 'form' ? `
          <div class="iw-progress-bar" role="region" aria-label="Form progress">
            ${this.renderProgressBar()}
          </div>

          <div class="iw-content" id="iw-content" role="region" aria-live="polite" aria-atomic="true">
            ${this.renderStep(step)}
          </div>

          <div class="iw-footer" id="iw-footer">
            ${this.renderFooter(step)}
          </div>
        ` : `
          <div class="iw-content iw-chat-container" id="iw-content"
               role="region" aria-live="polite" aria-atomic="false">
            ${this.renderChatMode()}
          </div>
        `}
        <div class="iw-version">v${WIDGET_VERSION}</div>
      </div>
    `;
  }

  private renderProgressBar(): string {
    const steps: { key: Step; label: string }[] = [
      { key: 'details', label: 'Details' },
      { key: 'questions', label: 'Questions' },
      { key: 'creating', label: 'Create' },
    ];

    const currentIndex = steps.findIndex((s) => s.key === this.state.step);

    return steps
      .map((step, index) => {
        let className = 'iw-step';
        const isSuccess = this.state.step === 'success';
        const isError = this.state.step === 'error';

        if (isSuccess) {
          className += ' completed';
        } else if (isError) {
          className += ' error';
        } else if (index < currentIndex) {
          className += ' completed';
        } else if (index === currentIndex) {
          className += ' active';
        }

        let dotContent: string;
        if (isSuccess) {
          dotContent = '✓';
        } else if (isError) {
          dotContent = '✕';
        } else if (index < currentIndex) {
          dotContent = '✓';
        } else {
          dotContent = String(index + 1);
        }

        return `
          <div class="${className}">
            <div class="iw-step-dot">${dotContent}</div>
            <span class="iw-step-label">${step.label}</span>
          </div>
        `;
      })
      .join('');
  }

  private renderStep(step: Step): string {
    switch (step) {
      case 'details':
        return this.renderDetailsStep();
      case 'questions':
        return this.renderQuestionsStep();
      case 'creating':
        return this.renderCreatingStep();
      case 'success':
        return this.renderSuccessStep();
      case 'error':
        return this.renderErrorStep();
      default:
        return '';
    }
  }

  private renderDetailsStep(): string {
    const hasScreenshot = this.state.screenshotPreviews.length > 0;
    const hasElement = this.state.selectedElement !== null;
    const { issueType } = this.state;

    return `
      <div class="iw-form-group">
        <label class="iw-label">Feedback Type</label>
        <div class="iw-type-selector">
          <button type="button" class="iw-type-btn ${issueType === 'bug' ? 'active' : ''}" data-type="bug">
            <span class="iw-type-icon">🐛</span>
            <span>Bug</span>
          </button>
          <button type="button" class="iw-type-btn ${issueType === 'suggestion' ? 'active' : ''}" data-type="suggestion">
            <span class="iw-type-icon">💡</span>
            <span>Suggestion</span>
          </button>
          <button type="button" class="iw-type-btn ${issueType === 'question' ? 'active' : ''}" data-type="question">
            <span class="iw-type-icon">❓</span>
            <span>Question</span>
          </button>
        </div>
      </div>

      <div class="iw-form-group">
        <label class="iw-label">Title *</label>
        <input type="text" class="iw-input" id="iw-title"
               placeholder="Brief description of the issue"
               value="${this.escapeHtml(this.state.title)}">
      </div>

      <div class="iw-form-group">
        <label class="iw-label">Description</label>
        <textarea class="iw-textarea" id="iw-description"
                  placeholder="Provide more details about the issue...">${this.escapeHtml(this.state.description)}</textarea>
      </div>

      <div class="iw-form-group">
        <label class="iw-label">Attachments</label>

        <div class="iw-attachments-grid">
          <div class="iw-attachment-btn ${hasScreenshot ? 'active' : ''}" id="iw-screenshot-btn">
            ${ICONS.camera}
            <span>Screenshot</span>
          </div>
          <div class="iw-attachment-btn" id="iw-upload-btn">
            ${ICONS.upload}
            <span>Upload</span>
          </div>
          <div class="iw-attachment-btn ${hasElement ? 'active' : ''}" id="iw-element-btn">
            ${ICONS.crosshair}
            <span>Seleziona</span>
          </div>
        </div>

        <input type="file" accept="image/*" class="iw-file-input" id="iw-file-input">

        <div class="iw-preview-area">
          ${hasScreenshot ? `
            <div class="iw-preview-image">
              <img src="${this.state.screenshotPreviews[0]}" alt="Screenshot">
              <button class="iw-preview-remove" id="iw-remove-screenshot">&times;</button>
            </div>
          ` : ''}

          ${hasElement ? this.renderElementInfo() : ''}
        </div>
      </div>

      ${this.state.error ? `<div class="iw-error">${this.state.error}</div>` : ''}
    `;
  }

  private renderElementInfo(): string {
    const el = this.state.selectedElement;
    if (!el) return '';

    return `
      <div class="iw-element-info">
        <div class="iw-element-info-header">
          <div class="iw-element-info-title">
            ${ICONS.crosshair}
            <span>Componente selezionato</span>
          </div>
          <button class="iw-element-info-remove" id="iw-remove-element">&times;</button>
        </div>
        <div class="iw-element-info-row">
          <span class="iw-element-info-label">Tag:</span>
          <span class="iw-element-info-value">${el.tagName}</span>
        </div>
        <div class="iw-element-info-row">
          <span class="iw-element-info-label">ID:</span>
          <span class="iw-element-info-value ${el.id ? '' : 'empty'}">${el.id || 'nessuno'}</span>
        </div>
        <div class="iw-element-info-row">
          <span class="iw-element-info-label">Classes:</span>
          <span class="iw-element-info-value ${el.classes.length ? '' : 'empty'}">${el.classes.length ? el.classes.join(' ') : 'nessuna'}</span>
        </div>
        <div class="iw-element-info-row">
          <span class="iw-element-info-label">Test ID:</span>
          <span class="iw-element-info-value ${el.dataTestId ? '' : 'empty'}">${el.dataTestId || 'nessuno'}</span>
        </div>
      </div>
    `;
  }

  private renderQuestionsStep(): string {
    return this.state.questions
      .map(
        (q) => `
        <div class="iw-question">
          <div class="iw-question-text">${q.question}</div>
          <div class="iw-question-why">${q.why}</div>
          <textarea class="iw-textarea"
                    data-question-id="${q.id}"
                    placeholder="Your answer...">${this.escapeHtml(this.state.answers[q.id] || '')}</textarea>
        </div>
      `
      )
      .join('');
  }

  private renderCreatingStep(): string {
    return `
      ${this.state.progressMessages
        .map(
          (msg) => `
        <div class="iw-progress-message">
          <div class="iw-spinner"></div>
          <span>${msg}</span>
        </div>
      `
        )
        .join('')}
      ${this.state.error ? `<div class="iw-error">${this.state.error}</div>` : ''}
    `;
  }

  private renderSuccessStep(): string {
    const issue = this.state.createdIssue;
    if (!issue) return '';

    const linearSynced = issue.linear_synced !== false;
    const warningHtml = !linearSynced && issue.linear_error
      ? `<div class="iw-warning">⚠️ Linear sync failed: ${this.escapeHtml(issue.linear_error)}</div>`
      : '';

    // Build links section
    const links: string[] = [];

    // TurboWrap link (always available)
    if (issue.turbowrap_url) {
      links.push(`<a href="${issue.turbowrap_url}" target="_blank" rel="noopener" class="iw-link-btn iw-link-turbowrap">
        📋 TurboWrap
      </a>`);
    }

    // Linear link (if synced)
    if (issue.url) {
      links.push(`<a href="${issue.url}" target="_blank" rel="noopener" class="iw-link-btn iw-link-linear">
        ↗ ${issue.identifier}
      </a>`);
    }

    const linksHtml = links.length > 0
      ? `<div class="iw-success-links">${links.join('')}</div>`
      : `<span class="iw-local-id">${issue.identifier}</span>`;

    return `
      <div class="iw-success">
        <div class="iw-success-icon">${ICONS.check}</div>
        <h3>Issue Created!</h3>
        <p>Your issue has been successfully created${linearSynced ? ' and synced' : ' locally'}.</p>
        ${linksHtml}
        ${warningHtml}
      </div>
    `;
  }

  private renderErrorStep(): string {
    return `
      <div class="iw-error-final">
        <div class="iw-error-icon">${ICONS.close}</div>
        <h3>Something went wrong</h3>
        <p class="iw-error-message">${this.escapeHtml(this.state.error || 'An unexpected error occurred')}</p>
        <div class="iw-error-actions">
          <button class="iw-btn iw-btn-secondary" id="iw-error-retry">Try Again</button>
          <button class="iw-btn iw-btn-primary" id="iw-error-close">Close</button>
        </div>
      </div>
    `;
  }

  private renderChatMode(): string {
    const { chatMessages, chatInput, chatIsStreaming, chatStreamingContent, createdIssue } = this.state;

    const messagesHtml = chatMessages.length === 0
      ? `
        <div class="iw-chat-welcome">
          <h3>Ciao! Come posso aiutarti?</h3>
          <p>Descrivi il problema o il suggerimento che vuoi segnalare.</p>
        </div>
      `
      : chatMessages
          .map((msg) => `
            <div class="iw-chat-message iw-chat-${msg.role} ${msg.isStreaming ? 'iw-chat-streaming' : ''}">
              <div class="iw-chat-avatar">${msg.role === 'user' ? 'Tu' : 'AI'}</div>
              <div class="iw-chat-content">${this.escapeHtml(msg.content)}</div>
            </div>
          `)
          .join('');

    // Show streaming message if active
    const streamingHtml = chatIsStreaming && chatStreamingContent
      ? `
        <div class="iw-chat-message iw-chat-assistant iw-chat-streaming">
          <div class="iw-chat-avatar">AI</div>
          <div class="iw-chat-content">${this.escapeHtml(chatStreamingContent)}</div>
        </div>
      `
      : '';

    // Show issue created success
    const successHtml = createdIssue
      ? `
        <div class="iw-chat-issue-created">
          <div class="iw-check-icon">${ICONS.check}</div>
          <span>Issue creato!</span>
          ${createdIssue.url
            ? `<a href="${createdIssue.url}" target="_blank" rel="noopener">${createdIssue.identifier}</a>`
            : `<span class="iw-local-id">${createdIssue.identifier}</span>`
          }
          ${createdIssue.linear_synced === false && createdIssue.linear_error
            ? `<div class="iw-warning-small">⚠️ ${this.escapeHtml(createdIssue.linear_error)}</div>`
            : ''
          }
        </div>
      `
      : '';

    return `
      <div class="iw-chat-messages" id="iw-chat-messages">
        ${messagesHtml}
        ${streamingHtml}
        ${successHtml}
      </div>

      <div class="iw-chat-input-area">
        <textarea
          class="iw-chat-input"
          id="iw-chat-input"
          placeholder="Descrivi il problema..."
          ${chatIsStreaming ? 'disabled' : ''}
        >${this.escapeHtml(chatInput)}</textarea>
        <button
          class="iw-chat-send"
          id="iw-chat-send"
          ${chatIsStreaming || !chatInput.trim() ? 'disabled' : ''}
        >
          ${ICONS.send}
        </button>
      </div>

      ${this.state.error ? `<div class="iw-error">${this.state.error}</div>` : ''}
    `;
  }

  private renderFooter(step: Step): string {
    const isNextDisabled = this.state.isLoading || this.state.isCapturingScreenshot;

    switch (step) {
      case 'details':
        return `
          <div></div>
          <button class="iw-btn iw-btn-primary" id="iw-next" ${isNextDisabled ? 'disabled' : ''}>
            ${this.state.isLoading ? '<div class="iw-spinner"></div>' : ''}
            <span>Analyze</span>
          </button>
        `;
      case 'questions':
        return `
          <button class="iw-btn iw-btn-secondary" id="iw-back">Back</button>
          <button class="iw-btn iw-btn-primary" id="iw-next" ${isNextDisabled ? 'disabled' : ''}>
            ${this.state.isLoading ? '<div class="iw-spinner"></div>' : ''}
            <span>Create Issue</span>
          </button>
        `;
      case 'creating':
        return `<div></div><div></div>`;
      case 'success':
        return `
          <div></div>
          <button class="iw-btn iw-btn-primary" id="iw-done">Done</button>
        `;
      default:
        return '';
    }
  }

  private initFocusTrap(): void {
    const modal = this.shadow.getElementById('iw-modal');
    if (!modal) return;

    const focusableElements = modal.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );

    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

    // Focus first element when modal opens
    if (firstElement && this.state.isOpen) {
      setTimeout(() => firstElement.focus(), 50);
    }

    // Trap focus on Tab
    const trapFocus = (e: Event) => {
      const keyEvent = e as KeyboardEvent;
      if (!this.state.isOpen) return;

      if (keyEvent.key === 'Tab') {
        if (keyEvent.shiftKey) {
          // Shift + Tab on first element -> go to last
          if (this.shadow.activeElement === firstElement) {
            keyEvent.preventDefault();
            lastElement?.focus();
          }
        } else {
          // Tab on last element -> go to first
          if (this.shadow.activeElement === lastElement) {
            keyEvent.preventDefault();
            firstElement?.focus();
          }
        }
      }

      // Escape key closes modal
      if (keyEvent.key === 'Escape' && this.state.isOpen) {
        keyEvent.preventDefault();
        this.close();
      }
    };

    this.shadow.addEventListener('keydown', trapFocus);
  }

  private attachEventListeners(): void {
    // Remove old listeners first to prevent duplicates
    this.removeEventListeners();

    const trigger = this.shadow.getElementById('iw-trigger');
    const overlay = this.shadow.getElementById('iw-overlay');
    const closeBtn = this.shadow.getElementById('iw-close');

    const openHandler = () => this.open();
    const closeHandler = () => this.close();
    const overlayCloseHandler = () => this.close();

    trigger?.addEventListener('click', openHandler);
    overlay?.addEventListener('click', overlayCloseHandler);
    closeBtn?.addEventListener('click', closeHandler);

    // Store handlers for later removal
    this.eventHandlers.set('trigger-click', openHandler);
    this.eventHandlers.set('overlay-click', overlayCloseHandler);
    this.eventHandlers.set('close-click', closeHandler);

    // Main click handler - stored for removal
    const shadowClickHandler = (e: Event) => {
      const target = e.target as HTMLElement;

      if (target.id === 'iw-next' || target.closest('#iw-next')) {
        this.handleNext();
      } else if (target.id === 'iw-back' || target.closest('#iw-back')) {
        this.handleBack();
      } else if (target.id === 'iw-done' || target.closest('#iw-done')) {
        this.close();
        this.reset();
      } else if (target.id === 'iw-screenshot-btn' || target.closest('#iw-screenshot-btn')) {
        this.handleScreenshotCapture();
      } else if (target.id === 'iw-upload-btn' || target.closest('#iw-upload-btn')) {
        this.handleUploadClick();
      } else if (target.id === 'iw-element-btn' || target.closest('#iw-element-btn')) {
        this.handleElementPick();
      } else if (target.id === 'iw-remove-screenshot') {
        this.handleRemoveScreenshot();
      } else if (target.id === 'iw-remove-element') {
        this.handleRemoveElement();
      }

      // Handle issue type selection
      const typeBtn = target.closest('.iw-type-btn') as HTMLElement;
      if (typeBtn && typeBtn.dataset.type) {
        this.state.issueType = typeBtn.dataset.type as IssueType;
        this.update();
      }

      // Handle mode selector
      const modeBtn = target.closest('.iw-mode-btn') as HTMLElement;
      if (modeBtn && modeBtn.dataset.mode) {
        this.handleModeSwitch(modeBtn.dataset.mode as WidgetMode);
      }

      // Handle chat send button
      if (target.id === 'iw-chat-send' || target.closest('#iw-chat-send')) {
        this.handleChatSend();
      }

      // Handle error state buttons
      if (target.id === 'iw-error-retry' || target.closest('#iw-error-retry')) {
        this.handleErrorRetry();
      } else if (target.id === 'iw-error-close' || target.closest('#iw-error-close')) {
        this.close();
        this.reset();
      }
    };
    this.shadow.addEventListener('click', shadowClickHandler);
    this.eventHandlers.set('shadow-click', shadowClickHandler);

    // Change handler - stored for removal
    const shadowChangeHandler = (e: Event) => {
      const target = e.target as HTMLInputElement;
      if (target.id === 'iw-file-input' && target.files?.length) {
        this.handleFileUpload(target.files[0]);
      }
    };
    this.shadow.addEventListener('change', shadowChangeHandler);
    this.eventHandlers.set('shadow-change', shadowChangeHandler);

    // Input handler - stored for removal
    const shadowInputHandler = (e: Event) => {
      const target = e.target as HTMLInputElement | HTMLTextAreaElement;

      if (target.id === 'iw-title') {
        this.state.title = target.value;
      } else if (target.id === 'iw-description') {
        this.state.description = target.value;
      } else if (target.dataset.questionId) {
        const qId = parseInt(target.dataset.questionId, 10);
        this.state.answers[qId] = target.value;
      } else if (target.id === 'iw-chat-input') {
        this.state.chatInput = target.value;
        // Update send button state
        const sendBtn = this.shadow.getElementById('iw-chat-send') as HTMLButtonElement;
        if (sendBtn) {
          sendBtn.disabled = this.state.chatIsStreaming || !target.value.trim();
        }
      }
    };
    this.shadow.addEventListener('input', shadowInputHandler);
    this.eventHandlers.set('shadow-input', shadowInputHandler);

    // Keydown handler for Enter key in chat - stored for removal
    const shadowKeydownHandler = (e: Event) => {
      const target = e.target as HTMLTextAreaElement;
      const keyEvent = e as KeyboardEvent;
      if (target.id === 'iw-chat-input' && keyEvent.key === 'Enter' && !keyEvent.shiftKey) {
        e.preventDefault();
        if (!this.state.chatIsStreaming && this.state.chatInput.trim()) {
          this.handleChatSend();
        }
      }
    };
    this.shadow.addEventListener('keydown', shadowKeydownHandler);
    this.eventHandlers.set('shadow-keydown', shadowKeydownHandler);
  }

  private removeEventListeners(): void {
    const trigger = this.shadow.getElementById('iw-trigger');
    const overlay = this.shadow.getElementById('iw-overlay');
    const closeBtn = this.shadow.getElementById('iw-close');

    const openHandler = this.eventHandlers.get('trigger-click');
    const overlayCloseHandler = this.eventHandlers.get('overlay-click');
    const closeHandler = this.eventHandlers.get('close-click');

    if (openHandler && trigger) {
      trigger.removeEventListener('click', openHandler);
    }
    if (overlayCloseHandler && overlay) {
      overlay.removeEventListener('click', overlayCloseHandler);
    }
    if (closeHandler && closeBtn) {
      closeBtn.removeEventListener('click', closeHandler);
    }

    // Remove shadow DOM event listeners
    const shadowClickHandler = this.eventHandlers.get('shadow-click');
    if (shadowClickHandler) {
      this.shadow.removeEventListener('click', shadowClickHandler);
    }
    const shadowChangeHandler = this.eventHandlers.get('shadow-change');
    if (shadowChangeHandler) {
      this.shadow.removeEventListener('change', shadowChangeHandler);
    }
    const shadowInputHandler = this.eventHandlers.get('shadow-input');
    if (shadowInputHandler) {
      this.shadow.removeEventListener('input', shadowInputHandler);
    }
    const shadowKeydownHandler = this.eventHandlers.get('shadow-keydown');
    if (shadowKeydownHandler) {
      this.shadow.removeEventListener('keydown', shadowKeydownHandler);
    }

    this.eventHandlers.clear();
  }

  private open(): void {
    this.state.isOpen = true;
    this.update();
    // Initialize focus trap after modal is rendered
    setTimeout(() => this.initFocusTrap(), 50);
    this.config.onOpen?.();
  }

  private close(): void {
    this.state.isOpen = false;
    this.update();
    this.config.onClose?.();
  }

  private reset(): void {
    // Cleanup chat session if active (non-blocking but tracked)
    if (this.state.chatSessionId) {
      this.client.deleteChatSession(this.state.chatSessionId).catch((error) => {
        console.warn('Chat session cleanup failed during reset:', error);
      });
    }

    this.state = {
      isOpen: false,
      step: 'details',
      issueType: 'bug',
      title: '',
      description: '',
      screenshots: [],
      screenshotPreviews: [],
      selectedElement: null,
      questions: [],
      answers: {},
      geminiInsights: '',
      tempSessionId: '',
      progressMessages: [],
      createdIssue: null,
      error: null,
      isLoading: false,
      isCapturingScreenshot: false,
      // Repository context (preserved from config)
      repositoryId: this.config.repositoryId || null,
      // Chat mode - reset
      mode: 'form',
      chatSessionId: null,
      chatMessages: [],
      chatInput: '',
      chatIsStreaming: false,
      chatStreamingContent: '',
    };
  }

  private update(): void {
    const modal = this.shadow.getElementById('iw-modal');
    const overlay = this.shadow.getElementById('iw-overlay');

    if (this.state.isOpen) {
      modal?.classList.add('open');
      overlay?.classList.add('open');
    } else {
      modal?.classList.remove('open');
      overlay?.classList.remove('open');
    }

    // Re-render the entire modal content for mode switching
    if (modal) {
      const { mode, step } = this.state;

      modal.innerHTML = `
        <div class="iw-header">
          <h2>${mode === 'chat' ? 'Chat' : 'Report an Issue'}</h2>
          <button class="iw-close" id="iw-close">&times;</button>
        </div>

        <div class="iw-mode-selector">
          <button class="iw-mode-btn ${mode === 'form' ? 'active' : ''}" data-mode="form">
            ${ICONS.form}
            <span>Report Issue</span>
          </button>
          <button class="iw-mode-btn ${mode === 'chat' ? 'active' : ''}" data-mode="chat">
            ${ICONS.chat}
            <span>Chat</span>
          </button>
        </div>

        ${mode === 'form' ? `
          <div class="iw-progress-bar">
            ${this.renderProgressBar()}
          </div>

          <div class="iw-content" id="iw-content">
            ${this.renderStep(step)}
          </div>

          <div class="iw-footer" id="iw-footer">
            ${this.renderFooter(step)}
          </div>
        ` : `
          <div class="iw-content iw-chat-container" id="iw-content">
            ${this.renderChatMode()}
          </div>
        `}
      `;

      // Reattach all event listeners after full DOM re-render
      this.attachEventListeners();
    }
  }

  private async handleScreenshotCapture(): Promise<void> {
    this.state.isCapturingScreenshot = true;
    this.update();

    try {
      // Hide widget during screenshot capture so it doesn't appear in the screenshot
      this.container.style.display = 'none';

      // Capture with rectangle selection - user can select area or use full screen
      const result = await captureScreenWithSelection(this.config.screenshotMethod);
      const compressed = await compressImage(result.blob);
      if (!compressed || compressed.size === 0) {
        throw new Error('Screenshot capture produced an empty image');
      }

      // Validate that the blob is a valid image type
      if (!compressed.type.startsWith('image/')) {
        throw new Error('Screenshot capture produced an invalid image format');
      }

      const dataUrl = await blobToDataUrl(compressed);

      // Revoke old blob URLs to prevent memory leaks
      this.blobUrls.forEach(url => {
        try {
          URL.revokeObjectURL(url);
        } catch (error) {
          console.warn('Blob URL revocation failed:', error);
        }
      });
      this.blobUrls = [];

      this.state.screenshots = [compressed];
      this.state.screenshotPreviews = [dataUrl];
      this.blobUrls.push(dataUrl);
      this.state.error = null;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to capture screenshot';
      // Don't show error if user cancelled - just silently continue
      if (errorMsg !== 'Screenshot selection cancelled') {
        this.state.error = errorMsg;
      }
      // Allow user to continue without screenshot
      this.state.screenshots = [];
      this.state.screenshotPreviews = [];
    } finally {
      // Always show widget again and reset capturing flag
      this.state.isCapturingScreenshot = false;
      try {
        this.container.style.display = '';
      } catch (error) {
        console.warn('Container display reset failed:', error);
      }
      this.update();
    }
  }

  private handleUploadClick(): void {
    const fileInput = this.shadow.getElementById('iw-file-input') as HTMLInputElement;
    fileInput?.click();
  }

  private async handleFileUpload(file: File): Promise<void> {
    try {
      // Validate file
      if (!file.type.startsWith('image/')) {
        this.state.error = 'Please upload an image file';
        this.update();
        return;
      }

      if (file.size > 10 * 1024 * 1024) { // 10MB limit
        this.state.error = 'File must be less than 10MB';
        this.update();
        return;
      }

      const compressed = await compressImage(file);
      const dataUrl = await blobToDataUrl(compressed);

      // Revoke old blob URLs to prevent memory leaks
      this.blobUrls.forEach(url => {
        try {
          URL.revokeObjectURL(url);
        } catch (error) {
          console.warn('Blob URL revocation failed:', error);
        }
      });
      this.blobUrls = [];

      this.state.screenshots = [compressed];
      this.state.screenshotPreviews = [dataUrl];
      this.blobUrls.push(dataUrl);
      this.state.error = null;
      this.update();
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to process file';
      this.state.error = errorMsg;
      this.update();
    }
  }

  private async handleElementPick(): Promise<void> {
    // Close the modal temporarily
    this.close();
    try {
      const elementInfo = await startElementPicker();
      if (elementInfo) {
        this.state.selectedElement = elementInfo;
        this.state.error = null;
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to pick element';
      this.state.error = errorMsg;
      // Continue without element selection
    } finally {
      // Guarantee modal reopens regardless of success or failure
      this.open();
    }
  }

  private handleRemoveScreenshot(): void {
    try {
      // Revoke blob URLs to prevent memory leaks
      this.blobUrls.forEach(url => {
        try {
          URL.revokeObjectURL(url);
        } catch (error) {
          console.warn('Blob URL revocation failed:', error);
        }
      });
      this.blobUrls = [];

      this.state.screenshots = [];
      this.state.screenshotPreviews = [];
      this.state.error = null;
      this.update();
    } catch {
      this.state.error = 'Failed to remove screenshot';
      this.update();
    }
  }

  private handleRemoveElement(): void {
    this.state.selectedElement = null;
    this.update();
  }

  private validateDetailsStep(): boolean {
    // Validate title
    if (!this.state.title.trim()) {
      this.state.error = 'Title is required';
      this.update();
      return false;
    }

    if (this.state.title.length > 500) {
      this.state.error = 'Title must be less than 500 characters';
      this.update();
      return false;
    }

    // Validate description (optional but if provided, must be reasonable)
    if (this.state.description.length > 5000) {
      this.state.error = 'Description must be less than 5000 characters';
      this.update();
      return false;
    }

    // Clear error if validation passed
    this.state.error = null;
    return true;
  }

  private validateQuestionsStep(): boolean {
    // Validate that all required questions have been answered
    for (const question of this.state.questions) {
      if (!this.state.answers[question.id]) {
        this.state.error = `Please answer: ${question.question}`;
        this.update();
        return false;
      }
    }

    this.state.error = null;
    return true;
  }

  private async handleNext(): Promise<void> {
    if (this.state.isCapturingScreenshot) {
      return;
    }

    if (this.state.step === 'details') {
      if (this.validateDetailsStep()) {
        await this.analyzeIssue();
      }
    } else if (this.state.step === 'questions') {
      if (this.validateQuestionsStep()) {
        await this.createIssue();
      }
    }
  }

  private handleBack(): void {
    if (this.state.step === 'questions') {
      this.state.step = 'details';
      this.update();
    }
  }

  private handleModeSwitch(mode: WidgetMode): void {
    if (mode === this.state.mode) return;

    this.state.mode = mode;

    // Reset chat state when switching to chat mode
    if (mode === 'chat') {
      this.state.chatMessages = [];
      this.state.chatInput = '';
      this.state.chatIsStreaming = false;
      this.state.chatStreamingContent = '';
      this.state.chatSessionId = null;
      this.state.createdIssue = null;
      this.state.error = null;
    }

    this.update();
  }

  private async handleChatSend(): Promise<void> {
    const message = this.state.chatInput.trim();

    // Validate message
    if (!message) {
      this.state.error = 'Message cannot be empty';
      this.update();
      return;
    }

    if (message.length > 2000) {
      this.state.error = 'Message must be less than 2000 characters';
      this.update();
      return;
    }

    if (this.state.chatIsStreaming) return;

    // Add user message to chat (HIGH ISSUE 5: use centralized method)
    const userMessage: ChatMessage = {
      id: this.generateId(),
      role: 'user',
      content: message,
      timestamp: new Date(),
    };
    this.addChatMessage(userMessage);
    this.state.chatInput = '';
    this.state.chatIsStreaming = true;
    this.state.chatStreamingContent = '';
    this.state.error = null;
    this.update();
    this.scrollChatToBottom();

    try {
      // Create session if not exists
      if (!this.state.chatSessionId) {
        const context: ChatContext = {
          pageUrl: window.location.href,
          pageTitle: document.title,
          selectedElement: this.state.selectedElement || undefined,
        };
        const session = await this.client.createChatSession({ context });
        this.state.chatSessionId = session.session_id;
      }

      // Send message and handle streaming response
      await this.client.sendChatMessage(
        this.state.chatSessionId,
        message,
        {
          pageUrl: window.location.href,
          pageTitle: document.title,
          selectedElement: this.state.selectedElement || undefined,
        },
        // onChunk
        (content: string) => {
          this.state.chatStreamingContent += content;
          this.updateChatContent();
          this.scrollChatToBottom();
        },
        // onAction
        (action: ChatActionData) => {
          if (action.type === 'create_issue') {
            this.handleChatCreateIssue(action.data);
          }
        },
        // onComplete
        () => {
          // Move streaming content to actual message (HIGH ISSUE 5: use centralized method)
          if (this.state.chatStreamingContent) {
            const assistantMessage: ChatMessage = {
              id: this.generateId(),
              role: 'assistant',
              content: this.state.chatStreamingContent,
              timestamp: new Date(),
            };
            this.addChatMessage(assistantMessage);
          }
          this.state.chatIsStreaming = false;
          this.state.chatStreamingContent = '';
          this.update();
        },
        // onError
        (error: string) => {
          this.state.error = error;
          this.state.chatIsStreaming = false;
          this.state.chatStreamingContent = '';
          this.update();
        }
      );
    } catch (error) {
      this.state.error = error instanceof Error ? error.message : 'Unknown error';
      this.state.chatIsStreaming = false;
      this.update();
    }
  }

  private async handleChatCreateIssue(data: { title: string; description: string; type: string }): Promise<void> {
    // Use the finalize endpoint to create the issue
    try {
      await this.client.finalizeIssue(
        {
          title: data.title,
          description: data.description,
          issueType: data.type as IssueType,
          userAnswers: {},
          geminiInsights: '',
          teamId: this.config.teamId,
          tempSessionId: this.state.chatSessionId || '',
          websiteLink: window.location.href,
          selectedElement: this.state.selectedElement || undefined,
        },
        () => {}, // onProgress - not needed for chat
        (result: IssueCreatedResult) => {
          this.state.createdIssue = result;
          this.update();
          this.scrollChatToBottom();
          this.config.onIssueCreated?.(result);
        },
        (error: string) => {
          // Add error as system message (HIGH ISSUE 5: use centralized method)
          const errorMessage: ChatMessage = {
            id: this.generateId(),
            role: 'system',
            content: `Errore nella creazione: ${error}`,
            timestamp: new Date(),
          };
          this.addChatMessage(errorMessage);

          this.update();
        }
      );
    } catch (error) {
      console.warn('Issue creation from chat failed:', error);
    }
  }

  private updateChatContent(): void {
    const content = this.shadow.getElementById('iw-content');
    if (content && this.state.mode === 'chat') {
      content.innerHTML = this.renderChatMode();
      // Reattach event listeners after DOM update
      this.attachEventListeners();
    }
  }

  private scrollChatToBottom(): void {
    const messagesEl = this.shadow.getElementById('iw-chat-messages');
    if (messagesEl) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  private async analyzeIssue(): Promise<void> {
    // Prevent duplicate requests
    if (this.state.isLoading) {
      console.warn('[IssueWidget] Analyze already in progress, ignoring duplicate call');
      return;
    }

    if (!this.state.title.trim()) {
      this.state.error = 'Please enter a title';
      this.update();
      return;
    }

    this.state.isLoading = true;
    this.state.error = null;
    this.update();

    try {
      // Note: proceeding without screenshot is allowed - user will see results without visual context

      await this.client.analyzeIssue(
        {
          title: this.state.title,
          description: this.state.description,
          issueType: this.state.issueType,
          screenshots: this.state.screenshots,
          repositoryId: this.state.repositoryId || undefined,
          websiteLink: window.location.href,
          selectedElement: this.state.selectedElement || undefined,
        },
        (msg) => {
          this.addProgressMessage(msg);
          this.update();
        },
        (result: AnalyzeResult) => {
          console.log('[IssueWidget] ✅ Analyze complete, received:', result);
          this.state.questions = result.questions;
          this.state.geminiInsights = result.geminiInsights;
          this.state.tempSessionId = result.tempSessionId;
          this.state.step = 'questions';
          this.state.isLoading = false;
          this.state.progressMessages = [];
          console.log('[IssueWidget] State updated, calling update()');
          this.update();
        },
        (error) => {
          this.state.error = error;
          this.state.isLoading = false;
          this.update();
          this.config.onError?.(new Error(error));
        }
      );
    } catch (error) {
      this.state.error = error instanceof Error ? error.message : 'Unknown error';
      this.state.isLoading = false;
      this.update();
    }
  }

  private async createIssue(): Promise<void> {
    // Prevent duplicate requests
    if (this.state.isLoading) {
      console.warn('[IssueWidget] Create already in progress, ignoring duplicate call');
      return;
    }

    this.state.step = 'creating';
    this.state.isLoading = true;
    this.state.progressMessages = [];
    this.update();

    try {
      await this.client.finalizeIssue(
        {
          title: this.state.title,
          description: this.state.description,
          issueType: this.state.issueType,
          userAnswers: this.state.answers,
          geminiInsights: this.state.geminiInsights,
          teamId: this.config.teamId,
          tempSessionId: this.state.tempSessionId,
          websiteLink: window.location.href,
          selectedElement: this.state.selectedElement || undefined,
          repositoryId: this.state.repositoryId || undefined,
        },
        (msg) => {
          this.addProgressMessage(msg);
          this.update();
        },
        (result: IssueCreatedResult) => {
          this.state.createdIssue = result;
          this.state.step = 'success';
          this.state.isLoading = false;
          this.update();
          this.config.onIssueCreated?.(result);
        },
        (error) => {
          this.state.error = error;
          this.state.step = 'error';  // Final error state - never go back!
          this.state.isLoading = false;
          this.update();
          this.config.onError?.(new Error(error));
        }
      );
    } catch (error) {
      this.state.error = error instanceof Error ? error.message : 'Unknown error';
      this.state.step = 'error';  // Final error state - never go back!
      this.state.isLoading = false;
      this.update();
    }
  }

  private handleErrorRetry(): void {
    // Reset to details step for a fresh retry
    this.state.step = 'details';
    this.state.error = null;
    this.state.isLoading = false;
    this.state.progressMessages = [];
    this.update();
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  private generateId(): string {
    // Use crypto.randomUUID if available, otherwise fallback to timestamp + random
    if (crypto && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
  }

  public async destroy(): Promise<void> {
    // 1. Cancel pending requests
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }

    // 2. Delete remote chat session (HIGH ISSUE 2: await session cleanup before other cleanup)
    const sessionId = this.state.chatSessionId;
    if (sessionId) {
      try {
        await this.client.deleteChatSession(sessionId);
      } catch (error) {
        console.warn('Session cleanup failed during destroy:', error);
      }
    }

    // 3. Revoke all blob URLs
    this.blobUrls.forEach(url => {
      try {
          URL.revokeObjectURL(url);
        } catch (error) {
          console.warn('Blob URL revocation failed:', error);
        }
    });
    this.blobUrls = [];

    // 4. Remove all event listeners
    this.removeEventListeners();

    // 5. Clear state
    this.state = {
      isOpen: false,
      step: 'details',
      issueType: 'bug',
      title: '',
      description: '',
      screenshots: [],
      screenshotPreviews: [],
      selectedElement: null,
      questions: [],
      answers: {},
      geminiInsights: '',
      tempSessionId: '',
      progressMessages: [],
      createdIssue: null,
      error: null,
      isLoading: false,
      isCapturingScreenshot: false,
      repositoryId: null,
      mode: 'form',
      chatSessionId: null,
      chatMessages: [],
      chatInput: '',
      chatIsStreaming: false,
      chatStreamingContent: '',
    };

    // 6. Remove DOM
    try {
      this.container.remove();
    } catch (error) {
      console.warn('Container removal failed:', error);
    }

    // 7. Trigger callback
    this.config.onClose?.();
  }
}
