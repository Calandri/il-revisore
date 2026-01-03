export const WIDGET_STYLES = `
:host {
  --iw-accent: #6366f1;
  --iw-accent-hover: #5558e3;
  --iw-bg: #ffffff;
  --iw-bg-secondary: #f9fafb;
  --iw-text: #111827;
  --iw-text-secondary: #6b7280;
  --iw-border: #e5e7eb;
  --iw-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  --iw-radius: 12px;
  --iw-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

:host(.dark) {
  --iw-bg: #1f2937;
  --iw-bg-secondary: #374151;
  --iw-text: #f9fafb;
  --iw-text-secondary: #9ca3af;
  --iw-border: #4b5563;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.iw-trigger {
  position: fixed;
  z-index: 2147483647;
  padding: 14px;
  border-radius: 50px;
  background: linear-gradient(135deg, var(--iw-accent) 0%, #8b5cf6 100%);
  color: white;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);
  font-family: var(--iw-font);
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 0;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.iw-trigger span {
  max-width: 0;
  opacity: 0;
  white-space: nowrap;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.iw-trigger:hover {
  padding: 14px 20px;
  gap: 8px;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
}

.iw-trigger:hover span {
  max-width: 150px;
  opacity: 1;
}

.iw-trigger.bottom-right {
  bottom: 24px;
  right: 24px;
}

.iw-trigger.bottom-left {
  bottom: 24px;
  left: 24px;
}

.iw-trigger.top-right {
  top: 24px;
  right: 24px;
}

.iw-trigger.top-left {
  top: 24px;
  left: 24px;
}

.iw-trigger svg {
  width: 18px;
  height: 18px;
  fill: currentColor;
}

.iw-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  opacity: 0;
  visibility: hidden;
  transition: all 0.3s ease;
}

.iw-modal-overlay.open {
  opacity: 1;
  visibility: visible;
}

.iw-modal {
  position: fixed;
  z-index: 2147483647;
  background: var(--iw-bg);
  border-radius: var(--iw-radius);
  box-shadow: var(--iw-shadow);
  width: 420px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 100px);
  display: flex;
  flex-direction: column;
  font-family: var(--iw-font);
  color: var(--iw-text);
  transform: translateY(20px) scale(0.95);
  opacity: 0;
  visibility: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.iw-modal.open {
  transform: translateY(0) scale(1);
  opacity: 1;
  visibility: visible;
}

.iw-modal.bottom-right {
  bottom: 100px;
  right: 24px;
}

.iw-modal.bottom-left {
  bottom: 100px;
  left: 24px;
}

.iw-modal.top-right {
  top: 100px;
  right: 24px;
}

.iw-modal.top-left {
  top: 100px;
  left: 24px;
}

.iw-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--iw-border);
}

.iw-header h2 {
  font-size: 16px;
  font-weight: 600;
}

.iw-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--iw-text-secondary);
  font-size: 24px;
  line-height: 1;
  padding: 4px;
  border-radius: 6px;
  transition: all 0.2s;
}

.iw-close:hover {
  background: var(--iw-bg-secondary);
  color: var(--iw-text);
}

.iw-progress-bar {
  display: flex;
  padding: 8px 20px;
  gap: 6px;
  border-bottom: 1px solid var(--iw-border);
}

.iw-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.iw-step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--iw-bg-secondary);
  border: 1px solid var(--iw-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--iw-text-secondary);
  transition: all 0.3s;
}

.iw-step.active .iw-step-dot {
  background: var(--iw-accent);
  border-color: var(--iw-accent);
  color: white;
}

.iw-step.completed .iw-step-dot {
  background: #10b981;
  border-color: #10b981;
  color: white;
}

.iw-step-label {
  font-size: 9px;
  color: var(--iw-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.iw-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.iw-form-group {
  margin-bottom: 16px;
}

.iw-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 6px;
  color: var(--iw-text);
}

.iw-input,
.iw-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--iw-border);
  border-radius: 8px;
  font-size: 14px;
  font-family: var(--iw-font);
  background: var(--iw-bg);
  color: var(--iw-text);
  transition: border-color 0.2s;
}

.iw-input:focus,
.iw-textarea:focus {
  outline: none;
  border-color: var(--iw-accent);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.iw-textarea {
  min-height: 100px;
  resize: vertical;
}

.iw-screenshot-area {
  border: 2px dashed var(--iw-border);
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.iw-screenshot-area:hover {
  border-color: var(--iw-accent);
  background: rgba(99, 102, 241, 0.05);
}

.iw-screenshot-area.has-screenshot {
  border-style: solid;
  padding: 8px;
}

.iw-screenshot-preview {
  max-width: 100%;
  border-radius: 6px;
}

.iw-screenshot-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  color: var(--iw-text-secondary);
}

.iw-screenshot-text {
  font-size: 14px;
  color: var(--iw-text-secondary);
}

.iw-screenshot-hint {
  font-size: 12px;
  color: var(--iw-text-secondary);
  margin-top: 4px;
}

/* Attachments Grid - 3 buttons layout */
.iw-attachments-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.iw-attachment-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 8px;
  border: 1px solid var(--iw-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--iw-bg);
}

.iw-attachment-btn:hover {
  border-color: var(--iw-accent);
  background: rgba(99, 102, 241, 0.05);
}

.iw-attachment-btn.active {
  border-color: var(--iw-accent);
  background: rgba(99, 102, 241, 0.1);
}

.iw-attachment-btn svg {
  width: 24px;
  height: 24px;
  color: var(--iw-text-secondary);
}

.iw-attachment-btn:hover svg,
.iw-attachment-btn.active svg {
  color: var(--iw-accent);
}

.iw-attachment-btn span {
  font-size: 11px;
  color: var(--iw-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* Preview Area */
.iw-preview-area {
  min-height: 60px;
}

.iw-preview-image {
  position: relative;
  display: inline-block;
}

.iw-preview-image img {
  max-width: 100%;
  max-height: 150px;
  border-radius: 6px;
  border: 1px solid var(--iw-border);
}

.iw-preview-remove {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #ef4444;
  color: white;
  border: 2px solid var(--iw-bg);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
}

.iw-preview-remove:hover {
  background: #dc2626;
}

/* Element Info Box */
.iw-element-info {
  padding: 12px;
  background: var(--iw-bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--iw-border);
}

.iw-element-info-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.iw-element-info-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--iw-text);
  display: flex;
  align-items: center;
  gap: 6px;
}

.iw-element-info-title svg {
  width: 14px;
  height: 14px;
  color: var(--iw-accent);
}

.iw-element-info-remove {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--iw-text-secondary);
  padding: 2px;
}

.iw-element-info-remove:hover {
  color: #ef4444;
}

.iw-element-info-row {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
  font-size: 12px;
}

.iw-element-info-label {
  color: var(--iw-text-secondary);
  min-width: 60px;
}

.iw-element-info-value {
  color: var(--iw-text);
  font-family: monospace;
  word-break: break-all;
}

.iw-element-info-value.empty {
  color: var(--iw-text-secondary);
  font-style: italic;
}

/* Hidden file input */
.iw-file-input {
  display: none;
}

.iw-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--iw-border);
}

.iw-btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  font-family: var(--iw-font);
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.iw-btn-primary {
  background: var(--iw-accent);
  color: white;
  border: none;
}

.iw-btn-primary:hover:not(:disabled) {
  background: var(--iw-accent-hover);
}

.iw-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.iw-btn-secondary {
  background: var(--iw-bg);
  color: var(--iw-text);
  border: 1px solid var(--iw-border);
}

.iw-btn-secondary:hover {
  background: var(--iw-bg-secondary);
}

.iw-question {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--iw-bg-secondary);
  border-radius: 8px;
}

.iw-question-text {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
}

.iw-question-why {
  font-size: 12px;
  color: var(--iw-text-secondary);
  margin-bottom: 12px;
  font-style: italic;
}

.iw-question .iw-textarea {
  min-height: 60px;
}

.iw-progress-message {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--iw-bg-secondary);
  border-radius: 8px;
  margin-bottom: 12px;
}

.iw-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--iw-border);
  border-top-color: var(--iw-accent);
  border-radius: 50%;
  animation: iw-spin 0.8s linear infinite;
}

@keyframes iw-spin {
  to { transform: rotate(360deg); }
}

.iw-success {
  text-align: center;
  padding: 20px;
}

.iw-success-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  background: #10b981;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.iw-success h3 {
  font-size: 18px;
  margin-bottom: 8px;
}

.iw-success p {
  color: var(--iw-text-secondary);
  margin-bottom: 16px;
}

.iw-success a {
  color: var(--iw-accent);
  text-decoration: none;
  font-weight: 500;
}

.iw-success a:hover {
  text-decoration: underline;
}

/* Issue Type Selector */
.iw-type-selector {
  display: flex;
  gap: 8px;
}

.iw-type-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 6px;
  border: 1px solid var(--iw-border);
  border-radius: 8px;
  background: var(--iw-bg);
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--iw-font);
  font-size: 11px;
  color: var(--iw-text);
}

.iw-type-btn:hover {
  border-color: var(--iw-accent);
  background: rgba(99, 102, 241, 0.05);
}

.iw-type-btn.active {
  border-color: var(--iw-accent);
  background: rgba(99, 102, 241, 0.1);
  color: var(--iw-accent);
}

.iw-type-icon {
  font-size: 16px;
}

@media (max-width: 480px) {
  .iw-modal {
    width: 100%;
    max-width: none;
    height: 100%;
    max-height: none;
    border-radius: 0;
    inset: 0;
  }

  .iw-modal.bottom-right,
  .iw-modal.bottom-left,
  .iw-modal.top-right,
  .iw-modal.top-left {
    top: 0;
    bottom: 0;
    left: 0;
    right: 0;
  }
}

/* ==================== */
/* Chat Mode Styles     */
/* ==================== */

/* Mode Selector */
.iw-mode-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  padding: 4px;
  background: var(--iw-bg-secondary);
  border-radius: 10px;
}

.iw-mode-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--iw-font);
  font-size: 13px;
  font-weight: 500;
  color: var(--iw-text-secondary);
}

.iw-mode-btn:hover {
  color: var(--iw-text);
  background: rgba(99, 102, 241, 0.05);
}

.iw-mode-btn.active {
  background: var(--iw-bg);
  color: var(--iw-accent);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.iw-mode-btn svg {
  width: 16px;
  height: 16px;
}

/* Chat Container */
.iw-chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 350px;
}

/* Chat Messages */
.iw-chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.iw-chat-message {
  display: flex;
  gap: 8px;
  max-width: 85%;
  animation: iw-message-in 0.2s ease-out;
}

@keyframes iw-message-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.iw-chat-message.iw-chat-user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.iw-chat-message.iw-chat-assistant {
  align-self: flex-start;
}

.iw-chat-message.iw-chat-system {
  align-self: center;
  max-width: 90%;
}

.iw-chat-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.iw-chat-user .iw-chat-avatar {
  background: var(--iw-accent);
  color: white;
}

.iw-chat-assistant .iw-chat-avatar {
  background: var(--iw-bg-secondary);
  color: var(--iw-text-secondary);
}

.iw-chat-content {
  padding: 10px 14px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.iw-chat-user .iw-chat-content {
  background: var(--iw-accent);
  color: white;
  border-bottom-right-radius: 4px;
}

.iw-chat-assistant .iw-chat-content {
  background: var(--iw-bg-secondary);
  color: var(--iw-text);
  border-bottom-left-radius: 4px;
}

.iw-chat-system .iw-chat-content {
  background: rgba(99, 102, 241, 0.1);
  color: var(--iw-accent);
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 20px;
}

/* Streaming indicator */
.iw-chat-streaming .iw-chat-content::after {
  content: '';
  display: inline-block;
  width: 4px;
  height: 14px;
  background: currentColor;
  margin-left: 2px;
  animation: iw-blink 0.8s infinite;
  vertical-align: text-bottom;
}

@keyframes iw-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* Chat Input Area */
.iw-chat-input-area {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--iw-border);
  margin-top: auto;
}

.iw-chat-input {
  flex: 1;
  padding: 12px 14px;
  border: 1px solid var(--iw-border);
  border-radius: 12px;
  background: var(--iw-bg);
  color: var(--iw-text);
  font-family: var(--iw-font);
  font-size: 14px;
  resize: none;
  min-height: 44px;
  max-height: 120px;
  outline: none;
  transition: border-color 0.2s;
}

.iw-chat-input:focus {
  border-color: var(--iw-accent);
}

.iw-chat-input::placeholder {
  color: var(--iw-text-secondary);
}

.iw-chat-send {
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 12px;
  background: var(--iw-accent);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.iw-chat-send:hover:not(:disabled) {
  background: var(--iw-accent-hover);
  transform: scale(1.05);
}

.iw-chat-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.iw-chat-send svg {
  width: 18px;
  height: 18px;
}

/* Chat Welcome */
.iw-chat-welcome {
  text-align: center;
  padding: 24px 16px;
  color: var(--iw-text-secondary);
}

.iw-chat-welcome h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--iw-text);
  margin-bottom: 8px;
}

.iw-chat-welcome p {
  font-size: 14px;
  line-height: 1.5;
}

/* Chat Issue Created Success */
.iw-chat-issue-created {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: rgba(34, 197, 94, 0.1);
  border-radius: 12px;
  margin: 8px 0;
}

.iw-chat-issue-created .iw-check-icon {
  width: 32px;
  height: 32px;
  color: #22c55e;
}

.iw-chat-issue-created a {
  color: var(--iw-accent);
  text-decoration: none;
  font-weight: 500;
}

.iw-chat-issue-created a:hover {
  text-decoration: underline;
}

/* Mobile adjustments for chat */
@media (max-width: 480px) {
  .iw-chat-messages {
    padding: 8px 0;
  }

  .iw-chat-message {
    max-width: 90%;
  }

  .iw-chat-input-area {
    padding: 8px 0;
  }

  .iw-chat-send {
    width: 48px;
    height: 48px;
  }
}

.iw-version {
  position: absolute;
  bottom: 4px;
  right: 8px;
  font-size: 9px;
  font-style: italic;
  color: var(--iw-text-secondary);
  opacity: 0.5;
  font-family: var(--iw-font);
  pointer-events: none;
  user-select: none;
}
`;
