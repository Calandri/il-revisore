import { IssueWidget } from './widget';
import type { WidgetConfig } from './api/types';

export { IssueWidget };
export type { WidgetConfig };
export type {
  AnalyzeRequest,
  AnalyzeResult,
  FinalizeRequest,
  IssueCreatedResult,
  Question,
} from './api/types';

// Auto-initialize from global config
declare global {
  interface Window {
    IssueWidgetConfig?: WidgetConfig;
    IssueWidget?: IssueWidget;
  }
}

function init(): void {
  if (typeof window === 'undefined') return;

  const config = window.IssueWidgetConfig;
  if (!config) {
    console.warn(
      '[IssueWidget] No configuration found. Please set window.IssueWidgetConfig before loading the script.'
    );
    return;
  }

  // Validate required fields
  if (!config.apiUrl) {
    console.error('[IssueWidget] Missing required config: apiUrl');
    return;
  }
  if (!config.apiKey) {
    console.error('[IssueWidget] Missing required config: apiKey');
    return;
  }
  if (!config.teamId) {
    console.error('[IssueWidget] Missing required config: teamId');
    return;
  }
  if (!config.repositoryId) {
    console.error('[IssueWidget] Missing required config: repositoryId');
    return;
  }

  // Create widget instance
  window.IssueWidget = new IssueWidget(config);
}

// Auto-init when DOM is ready
if (typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}
