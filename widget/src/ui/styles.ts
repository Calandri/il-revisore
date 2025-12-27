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
  padding: 14px 24px;
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
  gap: 8px;
  transition: all 0.2s ease;
}

.iw-trigger:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
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
  padding: 16px 20px;
  gap: 8px;
  border-bottom: 1px solid var(--iw-border);
}

.iw-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.iw-step-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--iw-bg-secondary);
  border: 2px solid var(--iw-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
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
  font-size: 11px;
  color: var(--iw-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
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
`;
