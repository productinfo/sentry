import {escapeSearchQuery} from 'app/utils/escapeSearchQuery';

describe('utils.escapeSearchQuery', function() {
  it('handles non-string values', function() {
    expect(escapeSearchQuery(null)).toBe('');
  });

  it('escapes strings without quotes', function() {
    expect(escapeSearchQuery('test')).toBe('test');
  });

  it('escapes strings with quotes', function() {
    expect(escapeSearchQuery('"test"')).toBe('"test"');
  });

  it('casts numbers to a string', function() {
    expect(escapeSearchQuery(1000)).toBe('1000');
  });
});
