import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);

Object.defineProperty(globalThis, 'ResizeObserver', {
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
});
