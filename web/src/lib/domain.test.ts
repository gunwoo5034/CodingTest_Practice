import { describe, expect, it } from 'vitest';
import { formatApiError, parseJsonValue, typeLabel } from './domain';

describe('domain helpers', () => {
  it('shows FastAPI validation details as one actionable Korean message', () => {
    const error = { detail: [{ loc: ['body', 'signature'], msg: 'Field required', type: 'missing' }] };
    expect(formatApiError(error)).toBe('signature: Field required');
  });

  it('rejects invalid test JSON before an API request can be made', () => {
    expect(() => parseJsonValue('[1,]')).toThrow('올바른 JSON 형식');
  });

  it('labels nested long arrays with their string boundary rule', () => {
    expect(typeLabel({ base: 'long', dimensions: 2 })).toBe('long[][] · 값은 문자열');
  });
});
