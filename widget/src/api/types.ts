export interface WidgetConfig {
  apiUrl: string;
  apiKey: string;
  teamId: string;
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  theme?: 'light' | 'dark' | 'auto';
  buttonText?: string;
  accentColor?: string;
  autoScreenshot?: boolean;
  screenshotMethod?: 'display-media' | 'html2canvas' | 'auto';
  onOpen?: () => void;
  onClose?: () => void;
  onIssueCreated?: (issue: IssueCreatedResult) => void;
  onError?: (error: Error) => void;
}

export interface ElementInfo {
  id: string | null;
  classes: string[];
  dataTestId: string | null;
  tagName: string;
  selector: string;
}

export interface AnalyzeRequest {
  title: string;
  description: string;
  screenshots: Blob[];
  figmaLink?: string;
  websiteLink?: string;
  selectedElement?: ElementInfo;
}

export interface Question {
  id: number;
  question: string;
  why: string;
}

export interface AnalyzeResult {
  questions: Question[];
  geminiInsights: string;
  tempSessionId: string;
}

export interface FinalizeRequest {
  title: string;
  description: string;
  userAnswers: Record<number, string>;
  geminiInsights: string;
  teamId: string;
  figmaLink?: string;
  websiteLink?: string;
  selectedElement?: ElementInfo;
}

export interface IssueCreatedResult {
  id: string;
  identifier: string;
  url: string;
}

export type SSEEventType = 'progress' | 'log' | 'complete' | 'error';

export interface SSEEvent {
  event: SSEEventType;
  data: unknown;
}
