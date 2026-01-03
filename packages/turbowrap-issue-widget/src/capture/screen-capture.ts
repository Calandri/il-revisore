import html2canvas from 'html2canvas';

export type CaptureMethod = 'display-media' | 'html2canvas' | 'auto';


export async function captureScreen(method: CaptureMethod = 'auto'): Promise<Blob> {
  if (method === 'html2canvas') {
    return captureWithHtml2Canvas();
  }

  if (method === 'display-media') {
    return captureWithDisplayMedia();
  }

  if (supportsDisplayMedia()) {
    try {
      return await captureWithDisplayMedia();
    } catch (error) {
      console.warn('Display media capture failed, falling back to html2canvas:', error);
    }
  }

  return captureWithHtml2Canvas();
}

export function supportsDisplayMedia(): boolean {
  return !!(
    navigator.mediaDevices &&
    'getDisplayMedia' in navigator.mediaDevices
  );
}

async function captureWithDisplayMedia(): Promise<Blob> {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: {
      displaySurface: 'browser',
    } as MediaTrackConstraints,
  });

  const track = stream.getVideoTracks()[0];

  try {
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;

    await new Promise<void>((resolve, reject) => {
      video.onloadedmetadata = () => {
        video.play().then(() => resolve()).catch(reject);
      };
      video.onerror = () => reject(new Error('Failed to load video'));
    });

    await new Promise((resolve) => requestAnimationFrame(resolve));

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Failed to get canvas context');
    ctx.drawImage(video, 0, 0);

    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (blob) resolve(blob);
          else reject(new Error('Failed to create blob'));
        },
        'image/png',
        1.0
      );
    });
  } finally {
    track.stop();
    stream.getTracks().forEach((t) => t.stop());
  }
}

async function captureWithHtml2Canvas(): Promise<Blob> {
  const canvas = await html2canvas(document.body, {
    useCORS: true,
    allowTaint: false,
    scale: Math.min(window.devicePixelRatio, 2),
    logging: false,
    windowWidth: document.documentElement.scrollWidth,
    windowHeight: document.documentElement.scrollHeight,
  });

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Failed to create blob'));
      },
      'image/png',
      0.9
    );
  });
}

export async function compressImage(blob: Blob, maxWidth = 1920): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(blob);

    img.onload = () => {
      try {
        URL.revokeObjectURL(url);
      } catch (error) {
        console.warn('Failed to revoke blob URL:', error);
      }

      let { width, height } = img;
      if (width > maxWidth) {
        height = (height * maxWidth) / width;
        width = maxWidth;
      }

      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Failed to get canvas context'));
        return;
      }

      ctx.drawImage(img, 0, 0, width, height);

      canvas.toBlob(
        (result) => {
          if (result) resolve(result);
          else reject(new Error('Failed to compress image'));
        },
        'image/png',
        0.85
      );
    };

    img.onerror = () => {
      try {
        URL.revokeObjectURL(url);
      } catch (error) {
        console.warn('Failed to revoke blob URL after error:', error);
      }
      reject(new Error('Failed to load image'));
    };

    img.src = url;
  });
}

export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        resolve(result);
      } else {
        reject(new Error('FileReader result is not a string'));
      }
    };
    reader.onerror = () => reject(new Error('Failed to read blob as data URL'));
    reader.readAsDataURL(blob);
  });
}
