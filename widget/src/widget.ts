import type {
  WidgetConfig,
  AnalyzeResult,
  IssueCreatedResult,
  Question,
} from './api/types';
import { IssueAPIClient } from './api/client';
import { captureScreen, compressImage, blobToDataUrl } from './capture/screen-capture';
import { WIDGET_STYLES } from './ui/styles';
import { ICONS } from './ui/icons';

type Step = 'details' | 'questions' | 'creating' | 'success';

interface WidgetState {
  isOpen: boolean;
  step: Step;
  title: string;
  description: string;
  screenshots: Blob[];
  screenshotPreviews: string[];
  questions: Question[];
  answers: Record<number, string>;
  geminiInsights: string;
  tempSessionId: string;
  progressMessages: string[];
  createdIssue: IssueCreatedResult | null;
  error: string | null;
  isLoading: boolean;
}

export class IssueWidget {
  private config: WidgetConfig;
  private client: IssueAPIClient;
  private container: HTMLElement;
  private shadow: ShadowRoot;
  private state: WidgetState;

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
      title: '',
      description: '',
      screenshots: [],
      screenshotPreviews: [],
      questions: [],
      answers: {},
      geminiInsights: '',
      tempSessionId: '',
      progressMessages: [],
      createdIssue: null,
      error: null,
      isLoading: false,
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

  private getHTML(): string {
    const position = this.config.position || 'bottom-right';
    const { step, isOpen } = this.state;

    return `
      <button class="iw-trigger ${position}" id="iw-trigger">
        ${ICONS.bug}
        <span>${this.config.buttonText}</span>
      </button>

      <div class="iw-modal-overlay ${isOpen ? 'open' : ''}" id="iw-overlay"></div>

      <div class="iw-modal ${position} ${isOpen ? 'open' : ''}" id="iw-modal">
        <div class="iw-header">
          <h2>Report an Issue</h2>
          <button class="iw-close" id="iw-close">&times;</button>
        </div>

        <div class="iw-progress-bar">
          ${this.renderProgressBar()}
        </div>

        <div class="iw-content" id="iw-content">
          ${this.renderStep(step)}
        </div>

        <div class="iw-footer" id="iw-footer">
          ${this.renderFooter(step)}
        </div>
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
        if (index < currentIndex || this.state.step === 'success') {
          className += ' completed';
        } else if (index === currentIndex) {
          className += ' active';
        }

        return `
          <div class="${className}">
            <div class="iw-step-dot">${index < currentIndex || this.state.step === 'success' ? '✓' : index + 1}</div>
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
      default:
        return '';
    }
  }

  private renderDetailsStep(): string {
    const hasScreenshot = this.state.screenshotPreviews.length > 0;

    return `
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
        <label class="iw-label">Screenshot</label>
        <div class="iw-screenshot-area ${hasScreenshot ? 'has-screenshot' : ''}" id="iw-screenshot-area">
          ${
            hasScreenshot
              ? `<img src="${this.state.screenshotPreviews[0]}" class="iw-screenshot-preview" alt="Screenshot">`
              : `
            <div class="iw-screenshot-icon">${ICONS.camera}</div>
            <div class="iw-screenshot-text">Click to capture screen</div>
            <div class="iw-screenshot-hint">or drag & drop an image</div>
          `
          }
        </div>
      </div>

      ${this.state.error ? `<div class="iw-error">${this.state.error}</div>` : ''}
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

    return `
      <div class="iw-success">
        <div class="iw-success-icon">${ICONS.check}</div>
        <h3>Issue Created!</h3>
        <p>Your issue has been successfully created and assigned.</p>
        <a href="${issue.url}" target="_blank" rel="noopener">${issue.identifier}</a>
      </div>
    `;
  }

  private renderFooter(step: Step): string {
    switch (step) {
      case 'details':
        return `
          <div></div>
          <button class="iw-btn iw-btn-primary" id="iw-next" ${this.state.isLoading ? 'disabled' : ''}>
            ${this.state.isLoading ? '<div class="iw-spinner"></div>' : ''}
            <span>Analyze</span>
          </button>
        `;
      case 'questions':
        return `
          <button class="iw-btn iw-btn-secondary" id="iw-back">Back</button>
          <button class="iw-btn iw-btn-primary" id="iw-next" ${this.state.isLoading ? 'disabled' : ''}>
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

  private attachEventListeners(): void {
    const trigger = this.shadow.getElementById('iw-trigger');
    const overlay = this.shadow.getElementById('iw-overlay');
    const closeBtn = this.shadow.getElementById('iw-close');

    trigger?.addEventListener('click', () => this.open());
    overlay?.addEventListener('click', () => this.close());
    closeBtn?.addEventListener('click', () => this.close());

    this.shadow.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;

      if (target.id === 'iw-next') {
        this.handleNext();
      } else if (target.id === 'iw-back') {
        this.handleBack();
      } else if (target.id === 'iw-done') {
        this.close();
        this.reset();
      } else if (target.id === 'iw-screenshot-area' || target.closest('#iw-screenshot-area')) {
        this.handleScreenshotCapture();
      }
    });

    this.shadow.addEventListener('input', (e) => {
      const target = e.target as HTMLInputElement | HTMLTextAreaElement;

      if (target.id === 'iw-title') {
        this.state.title = target.value;
      } else if (target.id === 'iw-description') {
        this.state.description = target.value;
      } else if (target.dataset.questionId) {
        const qId = parseInt(target.dataset.questionId, 10);
        this.state.answers[qId] = target.value;
      }
    });
  }

  private open(): void {
    this.state.isOpen = true;
    this.update();
    this.config.onOpen?.();
  }

  private close(): void {
    this.state.isOpen = false;
    this.update();
    this.config.onClose?.();
  }

  private reset(): void {
    this.state = {
      isOpen: false,
      step: 'details',
      title: '',
      description: '',
      screenshots: [],
      screenshotPreviews: [],
      questions: [],
      answers: {},
      geminiInsights: '',
      tempSessionId: '',
      progressMessages: [],
      createdIssue: null,
      error: null,
      isLoading: false,
    };
  }

  private update(): void {
    const modal = this.shadow.getElementById('iw-modal');
    const overlay = this.shadow.getElementById('iw-overlay');
    const content = this.shadow.getElementById('iw-content');
    const footer = this.shadow.getElementById('iw-footer');
    const progressBar = this.shadow.querySelector('.iw-progress-bar');

    if (this.state.isOpen) {
      modal?.classList.add('open');
      overlay?.classList.add('open');
    } else {
      modal?.classList.remove('open');
      overlay?.classList.remove('open');
    }

    if (content) content.innerHTML = this.renderStep(this.state.step);
    if (footer) footer.innerHTML = this.renderFooter(this.state.step);
    if (progressBar) progressBar.innerHTML = this.renderProgressBar();
  }

  private async handleScreenshotCapture(): Promise<void> {
    try {
      const blob = await captureScreen(this.config.screenshotMethod);
      const compressed = await compressImage(blob);
      const dataUrl = await blobToDataUrl(compressed);

      this.state.screenshots = [compressed];
      this.state.screenshotPreviews = [dataUrl];
      this.update();
    } catch (error) {
      console.error('Screenshot capture failed:', error);
    }
  }

  private async handleNext(): Promise<void> {
    if (this.state.step === 'details') {
      await this.analyzeIssue();
    } else if (this.state.step === 'questions') {
      await this.createIssue();
    }
  }

  private handleBack(): void {
    if (this.state.step === 'questions') {
      this.state.step = 'details';
      this.update();
    }
  }

  private async analyzeIssue(): Promise<void> {
    if (!this.state.title.trim()) {
      this.state.error = 'Please enter a title';
      this.update();
      return;
    }

    this.state.isLoading = true;
    this.state.error = null;
    this.update();

    try {
      await this.client.analyzeIssue(
        {
          title: this.state.title,
          description: this.state.description,
          screenshots: this.state.screenshots,
          websiteLink: window.location.href,
        },
        (msg) => {
          this.state.progressMessages.push(msg);
          this.update();
        },
        (result: AnalyzeResult) => {
          this.state.questions = result.questions;
          this.state.geminiInsights = result.geminiInsights;
          this.state.tempSessionId = result.tempSessionId;
          this.state.step = 'questions';
          this.state.isLoading = false;
          this.state.progressMessages = [];
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
    this.state.step = 'creating';
    this.state.isLoading = true;
    this.state.progressMessages = [];
    this.update();

    try {
      await this.client.finalizeIssue(
        {
          title: this.state.title,
          description: this.state.description,
          userAnswers: this.state.answers,
          geminiInsights: this.state.geminiInsights,
          teamId: this.config.teamId,
          websiteLink: window.location.href,
        },
        (msg) => {
          this.state.progressMessages.push(msg);
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
          this.state.step = 'questions';
          this.state.isLoading = false;
          this.update();
          this.config.onError?.(new Error(error));
        }
      );
    } catch (error) {
      this.state.error = error instanceof Error ? error.message : 'Unknown error';
      this.state.step = 'questions';
      this.state.isLoading = false;
      this.update();
    }
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  public destroy(): void {
    this.container.remove();
  }
}
