/**
 * MessageFormatter - Renders markdown content with syntax highlighting
 */

import { useMemo } from 'react';

export interface MessageFormatterProps {
  content: string;
  role?: 'user' | 'assistant' | 'system';
  className?: string;
}

/**
 * Formats message content with markdown support
 */
export function MessageFormatter({
  content,
  role = 'assistant',
  className = '',
}: MessageFormatterProps) {
  const formattedContent = useMemo(() => {
    return formatMarkdown(content, role);
  }, [content, role]);

  return (
    <div
      className={`message-content prose prose-sm dark:prose-invert max-w-none ${className}`}
      dangerouslySetInnerHTML={{ __html: formattedContent }}
    />
  );
}

/**
 * Parse and format markdown content to HTML
 */
function formatMarkdown(text: string, _role: string): string {
  if (!text) return '';

  let html = text;

  // Escape HTML first (except for code blocks which we'll handle separately)
  html = escapeHtmlExceptCode(html);

  // Code blocks with language (content already escaped by escapeHtmlExceptCode)
  html = html.replace(
    /```(\w+)?\n([\s\S]*?)```/g,
    (_, lang, code) => {
      // Language is already escaped, but use 'text' as safe default
      const language = lang || 'text';
      const escapedCode = code.trim();
      return `<div class="chat-code-block">
        <div class="chat-code-header">
          <span>${language}</span>
          <button class="copy-btn text-xs hover:text-white" onclick="navigator.clipboard.writeText(this.closest('.chat-code-block').querySelector('code').textContent)">Copy</button>
        </div>
        <pre class="chat-code-content"><code class="language-${language}">${escapedCode}</code></pre>
      </div>`;
    }
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-sm font-mono">$1</code>');

  // Callouts [!INFO], [!WARNING], [!ERROR], [!SUCCESS], [!TIP]
  html = html.replace(
    /\[!(INFO|WARNING|ERROR|SUCCESS|TIP)\]\s*\n?([\s\S]*?)(?=\n\n|\n\[!|$)/gi,
    (_, type, content) => {
      const typeClass = type.toLowerCase();
      const icons: Record<string, string> = {
        info: '💡',
        warning: '⚠️',
        error: '❌',
        success: '✅',
        tip: '💡',
      };
      return `<div class="chat-callout chat-callout-${typeClass}">
        <span class="mr-2">${icons[typeClass] || '📌'}</span>
        <span>${content.trim()}</span>
      </div>`;
    }
  );

  // Headers
  html = html.replace(/^######\s+(.+)$/gm, '<h6 class="text-xs font-semibold mt-3 mb-1">$1</h6>');
  html = html.replace(/^#####\s+(.+)$/gm, '<h5 class="text-sm font-semibold mt-3 mb-1">$1</h5>');
  html = html.replace(/^####\s+(.+)$/gm, '<h4 class="text-base font-semibold mt-4 mb-2">$1</h4>');
  html = html.replace(/^###\s+(.+)$/gm, '<h3 class="text-lg font-bold mt-4 mb-2">$1</h3>');
  html = html.replace(/^##\s+(.+)$/gm, '<h2 class="text-xl font-bold mt-5 mb-2 text-indigo-600 dark:text-indigo-400">$1</h2>');
  html = html.replace(/^#\s+(.+)$/gm, '<h1 class="text-2xl font-bold mt-6 mb-3 bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">$1</h1>');

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
  html = html.replace(/_(.+?)_/g, '<em>$1</em>');

  // Strikethrough
  html = html.replace(/~~(.+?)~~/g, '<del class="text-gray-500">$1</del>');

  // Highlight
  html = html.replace(/==(.+?)==/g, '<mark class="bg-yellow-200 dark:bg-yellow-800 px-0.5 rounded">$1</mark>');

  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr class="my-4 border-gray-300 dark:border-gray-600">');

  // Blockquotes
  html = html.replace(
    /^>\s+(.+)$/gm,
    '<blockquote class="border-l-4 border-gray-300 dark:border-gray-600 pl-4 italic text-gray-600 dark:text-gray-400">$1</blockquote>'
  );

  // Unordered lists
  html = html.replace(/^[-*]\s+(.+)$/gm, '<li class="ml-4">$1</li>');
  html = html.replace(/(<li.*<\/li>\n?)+/g, '<ul class="list-disc list-inside my-2">$&</ul>');

  // Ordered lists
  html = html.replace(/^\d+\.\s+(.+)$/gm, '<li class="ml-4">$1</li>');

  // Task lists
  html = html.replace(
    /^- \[x\]\s+(.+)$/gm,
    '<li class="ml-4 flex items-center gap-2"><input type="checkbox" checked disabled class="rounded text-indigo-500"><span class="line-through text-gray-500">$1</span></li>'
  );
  html = html.replace(
    /^- \[ \]\s+(.+)$/gm,
    '<li class="ml-4 flex items-center gap-2"><input type="checkbox" disabled class="rounded"><span>$1</span></li>'
  );

  // Links
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-indigo-600 dark:text-indigo-400 hover:underline">$1</a>'
  );

  // Auto-link URLs
  html = html.replace(
    /(?<!href="|src=")(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-indigo-600 dark:text-indigo-400 hover:underline">$1</a>'
  );

  // Tables
  html = formatTables(html);

  // Details/Summary
  html = html.replace(
    /<details>\s*<summary>([^<]+)<\/summary>([\s\S]*?)<\/details>/g,
    `<details class="my-2 border border-gray-200 dark:border-gray-700 rounded-lg">
      <summary class="px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 font-medium">$1</summary>
      <div class="px-3 py-2 border-t border-gray-200 dark:border-gray-700">$2</div>
    </details>`
  );

  // Paragraphs (double newlines)
  html = html.replace(/\n\n/g, '</p><p class="my-2">');

  // Single line breaks
  html = html.replace(/\n/g, '<br>');

  // Wrap in paragraph if needed
  if (!html.startsWith('<')) {
    html = `<p class="my-2">${html}</p>`;
  }

  return html;
}

/**
 * Format markdown tables to HTML
 */
function formatTables(html: string): string {
  const tableRegex = /\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)/g;

  return html.replace(tableRegex, (_match, headerRow, bodyRows) => {
    const headers = headerRow.split('|').filter((h: string) => h.trim());
    const rows = bodyRows.trim().split('\n').map((row: string) =>
      row.split('|').filter((c: string) => c.trim())
    );

    const headerHtml = headers
      .map((h: string) => `<th class="px-3 py-2 text-left font-semibold">${h.trim()}</th>`)
      .join('');

    const bodyHtml = rows
      .map((row: string[]) =>
        `<tr class="border-t border-gray-200 dark:border-gray-700">${row
          .map((cell: string) => `<td class="px-3 py-2">${cell.trim()}</td>`)
          .join('')}</tr>`
      )
      .join('');

    return `<table class="w-full my-3 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <thead class="bg-gray-50 dark:bg-gray-800">
        <tr>${headerHtml}</tr>
      </thead>
      <tbody>${bodyHtml}</tbody>
    </table>`;
  });
}

/**
 * Escape HTML characters
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Escape HTML but preserve code blocks (with their content also escaped)
 */
function escapeHtmlExceptCode(text: string): string {
  // Store code blocks with their content escaped
  const codeBlocks: string[] = [];
  let processed = text.replace(/```(\w+)?\n([\s\S]*?)```/g, (_match, lang, code) => {
    // Escape the language name and code content inside the block
    const escapedLang = lang ? escapeHtml(lang) : '';
    const escapedCode = escapeHtml(code);
    const escapedBlock = `\`\`\`${escapedLang}\n${escapedCode}\`\`\``;
    codeBlocks.push(escapedBlock);
    return `__CODE_BLOCK_${codeBlocks.length - 1}__`;
  });

  // Escape HTML in the rest of the text
  processed = processed
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Restore code blocks (already escaped)
  codeBlocks.forEach((block, i) => {
    processed = processed.replace(`__CODE_BLOCK_${i}__`, block);
  });

  return processed;
}
