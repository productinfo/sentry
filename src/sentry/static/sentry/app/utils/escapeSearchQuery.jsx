/**
 * Escapes search strings for use in events/issues search
 */
export function escapeSearchQuery(value) {
  // Cast numbers to string
  if (typeof value === 'number') {
    return `${value}`;
  }

  return typeof value === 'string' ? value.replace(/"/g, '"') : '';
}
