// The API sends UTC timestamps without a zone, which the browser would read as local time.
export function parseUtc(timestamp: string): Date {
  return new Date(/Z|[+-]\d\d:?\d\d$/.test(timestamp) ? timestamp : `${timestamp}Z`);
}
