/**
 * Rectangle selection overlay for screenshot cropping.
 * Allows users to draw a rectangle to select a specific area of the screen.
 */

export interface SelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RectangleSelectorOptions {
  imageBlob: Blob;
  onSelect: (rect: SelectionRect) => void;
  onCancel: () => void;
  onFullScreen: () => void;
}

const OVERLAY_STYLES = `
  .iw-rect-overlay {
    position: fixed;
    inset: 0;
    z-index: 2147483647;
    cursor: crosshair;
    background: rgba(0, 0, 0, 0.3);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }

  .iw-rect-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  .iw-rect-toolbar {
    position: fixed;
    top: 16px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 8px;
    padding: 8px 16px;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
    z-index: 10;
  }

  .iw-rect-btn {
    padding: 10px 16px;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s;
  }

  .iw-rect-btn-primary {
    background: #6366f1;
    color: white;
  }

  .iw-rect-btn-primary:hover {
    background: #5558e3;
  }

  .iw-rect-btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .iw-rect-btn-secondary {
    background: #f3f4f6;
    color: #374151;
  }

  .iw-rect-btn-secondary:hover {
    background: #e5e7eb;
  }

  .iw-rect-btn svg {
    width: 16px;
    height: 16px;
  }

  .iw-rect-hint {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 20px;
    background: rgba(0, 0, 0, 0.8);
    color: white;
    border-radius: 8px;
    font-size: 13px;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .iw-rect-hint kbd {
    background: rgba(255, 255, 255, 0.2);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 12px;
  }

  .iw-rect-dimensions {
    position: fixed;
    padding: 6px 10px;
    background: rgba(0, 0, 0, 0.8);
    color: white;
    border-radius: 4px;
    font-size: 12px;
    font-family: monospace;
    pointer-events: none;
    z-index: 10;
  }
`;

const ICONS = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  fullscreen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>',
  mouse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="6"/><line x1="12" y1="6" x2="12" y2="10"/></svg>',
};

export function showRectangleSelector(options: RectangleSelectorOptions): void {
  const { imageBlob, onSelect, onCancel, onFullScreen } = options;

  // Create overlay container
  const overlay = document.createElement('div');
  overlay.className = 'iw-rect-overlay';

  // Add styles
  const style = document.createElement('style');
  style.textContent = OVERLAY_STYLES;
  overlay.appendChild(style);

  // Create canvas for drawing
  const canvas = document.createElement('canvas');
  canvas.className = 'iw-rect-canvas';
  overlay.appendChild(canvas);

  // Create toolbar
  const toolbar = document.createElement('div');
  toolbar.className = 'iw-rect-toolbar';
  toolbar.innerHTML = `
    <button class="iw-rect-btn iw-rect-btn-secondary" id="iw-rect-fullscreen">
      ${ICONS.fullscreen}
      <span>Schermo intero</span>
    </button>
    <button class="iw-rect-btn iw-rect-btn-primary" id="iw-rect-confirm" disabled>
      ${ICONS.check}
      <span>Conferma</span>
    </button>
    <button class="iw-rect-btn iw-rect-btn-secondary" id="iw-rect-cancel">
      ${ICONS.x}
      <span>Annulla</span>
    </button>
  `;
  overlay.appendChild(toolbar);

  // Create hint
  const hint = document.createElement('div');
  hint.className = 'iw-rect-hint';
  hint.innerHTML = `${ICONS.mouse} Disegna un rettangolo per selezionare l'area • <kbd>ESC</kbd> annulla`;
  overlay.appendChild(hint);

  // Create dimensions display (hidden initially)
  const dimensions = document.createElement('div');
  dimensions.className = 'iw-rect-dimensions';
  dimensions.style.display = 'none';
  overlay.appendChild(dimensions);

  // State
  let isDrawing = false;
  let startX = 0;
  let startY = 0;
  let currentRect: SelectionRect | null = null;
  let imageLoaded = false;
  let image: HTMLImageElement | null = null;
  let scaleX = 1;
  let scaleY = 1;

  const ctx = canvas.getContext('2d')!;
  const confirmBtn = toolbar.querySelector('#iw-rect-confirm') as HTMLButtonElement;

  // Load the screenshot image
  const imageUrl = URL.createObjectURL(imageBlob);
  image = new Image();

  image.onload = () => {
    imageLoaded = true;

    // Set canvas size to window size
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    // Calculate scale to fit image in window
    scaleX = image!.width / canvas.width;
    scaleY = image!.height / canvas.height;

    // Draw the image scaled to fit
    ctx.drawImage(image!, 0, 0, canvas.width, canvas.height);

    // Add semi-transparent overlay
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  };

  image.src = imageUrl;

  // Helper to draw the selection
  function drawSelection(rect: SelectionRect): void {
    if (!image || !imageLoaded) return;

    // Redraw the image
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

    // Add semi-transparent overlay
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Clear the selected area to show the original image
    ctx.save();
    ctx.beginPath();
    ctx.rect(rect.x, rect.y, rect.width, rect.height);
    ctx.clip();
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    ctx.restore();

    // Draw selection border
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);

    // Draw corner handles
    const handleSize = 8;
    ctx.fillStyle = '#6366f1';
    const corners = [
      [rect.x, rect.y],
      [rect.x + rect.width, rect.y],
      [rect.x, rect.y + rect.height],
      [rect.x + rect.width, rect.y + rect.height],
    ];
    corners.forEach(([cx, cy]) => {
      ctx.fillRect(cx - handleSize / 2, cy - handleSize / 2, handleSize, handleSize);
    });

    // Update dimensions display
    const realWidth = Math.round(Math.abs(rect.width) * scaleX);
    const realHeight = Math.round(Math.abs(rect.height) * scaleY);
    dimensions.textContent = `${realWidth} × ${realHeight}`;
    dimensions.style.display = 'block';
    dimensions.style.left = `${rect.x + rect.width / 2}px`;
    dimensions.style.top = `${rect.y + rect.height + 10}px`;
    dimensions.style.transform = 'translateX(-50%)';
  }

  // Mouse event handlers
  function onMouseDown(e: MouseEvent): void {
    if (!imageLoaded || e.target !== canvas) return;

    isDrawing = true;
    startX = e.clientX;
    startY = e.clientY;
    currentRect = null;
    confirmBtn.disabled = true;
  }

  function onMouseMove(e: MouseEvent): void {
    if (!isDrawing || !imageLoaded) return;

    const x = Math.min(startX, e.clientX);
    const y = Math.min(startY, e.clientY);
    const width = Math.abs(e.clientX - startX);
    const height = Math.abs(e.clientY - startY);

    // Minimum selection size
    if (width > 10 && height > 10) {
      currentRect = { x, y, width, height };
      drawSelection(currentRect);
      confirmBtn.disabled = false;
    }
  }

  function onMouseUp(): void {
    isDrawing = false;
  }

  // Keyboard handler
  function onKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      cleanup();
      onCancel();
    } else if (e.key === 'Enter' && currentRect) {
      confirmSelection();
    }
  }

  // Confirm selection
  function confirmSelection(): void {
    if (!currentRect) return;

    // Convert screen coordinates to image coordinates
    const imageRect: SelectionRect = {
      x: Math.round(currentRect.x * scaleX),
      y: Math.round(currentRect.y * scaleY),
      width: Math.round(currentRect.width * scaleX),
      height: Math.round(currentRect.height * scaleY),
    };

    cleanup();
    onSelect(imageRect);
  }

  // Cleanup function
  function cleanup(): void {
    document.removeEventListener('keydown', onKeyDown);
    canvas.removeEventListener('mousedown', onMouseDown);
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    URL.revokeObjectURL(imageUrl);
    overlay.remove();
  }

  // Button handlers
  confirmBtn.addEventListener('click', confirmSelection);

  toolbar.querySelector('#iw-rect-cancel')!.addEventListener('click', () => {
    cleanup();
    onCancel();
  });

  toolbar.querySelector('#iw-rect-fullscreen')!.addEventListener('click', () => {
    cleanup();
    onFullScreen();
  });

  // Attach event listeners
  canvas.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
  document.addEventListener('keydown', onKeyDown);

  // Add to DOM
  document.body.appendChild(overlay);
}

/**
 * Crops an image blob to the specified rectangle.
 */
export async function cropImage(imageBlob: Blob, rect: SelectionRect): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(imageBlob);

    img.onload = () => {
      URL.revokeObjectURL(url);

      const canvas = document.createElement('canvas');
      canvas.width = rect.width;
      canvas.height = rect.height;

      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Failed to get canvas context'));
        return;
      }

      // Draw the cropped portion
      ctx.drawImage(
        img,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        0,
        0,
        rect.width,
        rect.height
      );

      canvas.toBlob(
        (blob) => {
          if (blob) resolve(blob);
          else reject(new Error('Failed to create cropped image blob'));
        },
        'image/png',
        1.0
      );
    };

    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Failed to load image for cropping'));
    };

    img.src = url;
  });
}
