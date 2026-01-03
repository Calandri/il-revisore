import type { ElementInfo } from '../api/types';

const PICKER_STYLES = `
  .element-picker-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: 2147483646;
    cursor: crosshair;
  }
  .element-picker-highlight {
    position: fixed;
    pointer-events: none;
    border: 2px solid #5E6AD2;
    background: rgba(94, 106, 210, 0.1);
    z-index: 2147483647;
    transition: all 0.1s ease;
  }
  .element-picker-tooltip {
    position: fixed;
    background: #1a1a2e;
    color: #fff;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
    font-family: monospace;
    z-index: 2147483647;
    pointer-events: none;
    max-width: 300px;
    word-break: break-all;
  }
`;

function generateSelector(element: HTMLElement): string {
  if (element.id) {
    return `#${element.id}`;
  }

  const tagName = element.tagName.toLowerCase();
  const classes = Array.from(element.classList)
    .filter((c) => !c.startsWith('element-picker'))
    .slice(0, 2)
    .join('.');

  if (classes) {
    return `${tagName}.${classes}`;
  }

  return tagName;
}

function extractElementInfo(element: HTMLElement): ElementInfo {
  return {
    id: element.id || null,
    classes: Array.from(element.classList).filter(
      (c) => !c.startsWith('element-picker')
    ),
    dataTestId: element.dataset.testid || element.dataset.testId || null,
    tagName: element.tagName.toLowerCase(),
    selector: generateSelector(element),
  };
}

export function startElementPicker(): Promise<ElementInfo | null> {
  return new Promise((resolve) => {
    const styleEl = document.createElement('style');
    styleEl.id = 'element-picker-styles';
    styleEl.textContent = PICKER_STYLES;
    document.head.appendChild(styleEl);

    const overlay = document.createElement('div');
    overlay.className = 'element-picker-overlay';

    const highlight = document.createElement('div');
    highlight.className = 'element-picker-highlight';
    highlight.style.display = 'none';

    const tooltip = document.createElement('div');
    tooltip.className = 'element-picker-tooltip';
    tooltip.style.display = 'none';

    document.body.appendChild(overlay);
    document.body.appendChild(highlight);
    document.body.appendChild(tooltip);

    let currentElement: HTMLElement | null = null;

    const cleanup = () => {
      overlay.remove();
      highlight.remove();
      tooltip.remove();
      styleEl.remove();
      document.removeEventListener('keydown', handleKeydown);
    };

    const handleMouseMove = (e: MouseEvent) => {
      overlay.style.pointerEvents = 'none';
      const target = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement;
      overlay.style.pointerEvents = 'auto';

      if (!target || target === document.body || target === document.documentElement) {
        highlight.style.display = 'none';
        tooltip.style.display = 'none';
        currentElement = null;
        return;
      }

      currentElement = target;
      const rect = target.getBoundingClientRect();

      highlight.style.display = 'block';
      highlight.style.top = `${rect.top}px`;
      highlight.style.left = `${rect.left}px`;
      highlight.style.width = `${rect.width}px`;
      highlight.style.height = `${rect.height}px`;

      const selector = generateSelector(target);
      tooltip.textContent = selector;
      tooltip.style.display = 'block';
      tooltip.style.top = `${Math.max(rect.top - 30, 5)}px`;
      tooltip.style.left = `${Math.min(rect.left, window.innerWidth - 200)}px`;
    };

    const handleClick = (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();

      if (currentElement) {
        const info = extractElementInfo(currentElement);
        cleanup();
        resolve(info);
      }
    };

    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        cleanup();
        resolve(null);
      }
    };

    overlay.addEventListener('mousemove', handleMouseMove);
    overlay.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKeydown);
  });
}
