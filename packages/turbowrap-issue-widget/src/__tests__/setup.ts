// Jest setup file
import '@testing-library/jest-dom';

// Mock crypto.randomUUID if not available
if (!globalThis.crypto) {
  globalThis.crypto = {
    randomUUID: () => {
      return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
    },
  } as any;
}

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

// Mock URL.createObjectURL and URL.revokeObjectURL
global.URL.createObjectURL = jest.fn(() => 'blob:mock-url');
global.URL.revokeObjectURL = jest.fn();

// Mock navigator.mediaDevices.getDisplayMedia
Object.defineProperty(navigator, 'mediaDevices', {
  value: {
    getDisplayMedia: jest.fn(),
  },
  writable: true,
});

// Mock FileReader
class MockFileReader {
  readAsDataURL = jest.fn(function() {
    setTimeout(() => {
      this.onload?.({
        target: { result: 'data:image/png;base64,mock' },
      });
    }, 0);
  });
}

global.FileReader = MockFileReader as any;
