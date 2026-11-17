import { describe, it, expect, vi } from 'vitest';
import { log4js, logUtil } from '@/utils/logger';

describe('logger', () => {
  describe('log4js.getLogger', () => {
    it('returns a logger with the correct category field', () => {
      const logger = log4js.getLogger('test-category');
      expect(logger.category).toBe('test-category');
    });

    it('same category called twice returns the same cached logger', () => {
      const a = log4js.getLogger('same-cat');
      const b = log4js.getLogger('same-cat');
      expect(a).toBe(b);
    });
  });

  describe('logUtil.info', () => {
    it('calls console.info with prefix and message', () => {
      const spy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
      const logger = log4js.getLogger('info-test');
      logUtil.info({ logger, message: 'hello info' });
      expect(spy).toHaveBeenCalled();
      const args = spy.mock.calls[0];
      expect(String(args?.[0])).toContain('[INFO]');
      expect(args?.[1]).toBe('hello info');
      spy.mockRestore();
    });

    it('passes data as third arg when provided', () => {
      const spy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
      const logger = log4js.getLogger('info-data');
      const data = { key: 'value' };
      logUtil.info({ logger, message: 'with data', data });
      const args = spy.mock.calls[0];
      expect(args?.[2]).toEqual(data);
      spy.mockRestore();
    });

    it('calls console.info with only two args when no data', () => {
      const spy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
      const logger = log4js.getLogger('info-nodata');
      logUtil.info({ logger, message: 'no data' });
      expect(spy.mock.calls[0]?.length).toBe(2);
      spy.mockRestore();
    });
  });

  describe('logUtil.warn', () => {
    it('calls console.warn with [WARN] prefix', () => {
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      const logger = log4js.getLogger('warn-test');
      logUtil.warn({ logger, message: 'warning' });
      expect(String(spy.mock.calls[0]?.[0])).toContain('[WARN]');
      spy.mockRestore();
    });
  });

  describe('logUtil.error', () => {
    it('calls console.error with [ERROR] prefix', () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const logger = log4js.getLogger('err-test');
      logUtil.error({ logger, message: 'error happened' });
      expect(String(spy.mock.calls[0]?.[0])).toContain('[ERROR]');
      spy.mockRestore();
    });
  });

  describe('logUtil.debug', () => {
    it('calls console.debug when isDebugEnabled returns true', () => {
      const spy = vi.spyOn(console, 'debug').mockImplementation(() => undefined);
      const mockLogger = {
        category: 'dbg',
        isDebugEnabled: () => true,
        isInfoEnabled: () => true,
        isWarnEnabled: () => true,
        isErrorEnabled: () => true,
      };
      logUtil.debug({ logger: mockLogger, message: 'debug msg' });
      expect(spy).toHaveBeenCalled();
      spy.mockRestore();
    });

    it('suppresses output when isDebugEnabled returns false', () => {
      const spy = vi.spyOn(console, 'debug').mockImplementation(() => undefined);
      const mockLogger = {
        category: 'dbg-off',
        isDebugEnabled: () => false,
        isInfoEnabled: () => true,
        isWarnEnabled: () => true,
        isErrorEnabled: () => true,
      };
      logUtil.debug({ logger: mockLogger, message: 'hidden' });
      expect(spy).not.toHaveBeenCalled();
      spy.mockRestore();
    });
  });
});
