export type IssueType = 'bug' | 'suggestion' | 'question';

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
  issueType: IssueType;
  screenshots: Blob[];
  repositoryId?: string;
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
  issueType: IssueType;
  userAnswers: Record<number, string>;
  geminiInsights: string;
  teamId: string;
  tempSessionId: string;
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

// --- Chat Mode Types ---

export type WidgetMode = 'form' | 'chat';

export interface ChatContext {
  repositoryId?: string;
  pageUrl?: string;
  pageTitle?: string;
  selectedElement?: ElementInfo;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
}

export interface ChatSessionResponse {
  session_id: string;
  message?: string;
}

export interface ChatActionData {
  type: 'create_issue';
  data: {
    title: string;
    description: string;
    type: 'bug' | 'suggestion';
  };
}
