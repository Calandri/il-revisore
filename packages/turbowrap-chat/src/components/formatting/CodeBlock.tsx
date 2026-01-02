/**
 * CodeBlock - Syntax highlighted code block component
 */

import { useState, useCallback } from 'react';

export interface CodeBlockProps {
  code: string;
  language?: string;
  className?: string;
}

/**
 * Renders a code block with copy functionality
 */
export function CodeBlock({
  code,
  language = 'text',
  className = '',
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, [code]);

  return (
    <div className={`chat-code-block ${className}`}>
      <div className="chat-code-header">
        <span className="text-gray-400">{language}</span>
        <button
          onClick={handleCopy}
          className="text-xs text-gray-400 hover:text-white transition-colors"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="chat-code-content overflow-x-auto">
        <code className={`language-${language}`}>{code}</code>
      </pre>
    </div>
  );
}
