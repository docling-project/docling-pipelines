/// <reference types="node" />
import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { server } from './mocks/server';

// Start MSW server before all tests, reset handlers after each, stop after all
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom does not implement these Web APIs
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ResizeObserver must be a proper constructor (class) — Carbon uses `new ResizeObserver()`
class ResizeObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
global.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

// Global module mocks — applied to every test file
vi.mock('@elyra/canvas', () => import('./mocks/modules/@elyra/canvas'));
vi.mock('log4js', () => import('./mocks/modules/log4js'));

// @carbon-labs/react-animated-header uses directory imports not supported in ESM test env
vi.mock('@carbon-labs/react-animated-header', () => ({
  AnimatedHeader: ({ children }: { children?: React.ReactNode }) => children ?? null,
  watsonXAnimatedLight: '',
  watsonXStaticLight: '',
  watsonXAnimatedDark: '',
  watsonXStaticDark: '',
}));
