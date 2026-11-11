// Shared URL guard for Google Flow pages.
// Compare the parsed hostname instead of a substring match, otherwise
// "https://evil.test/flow.google.com" passes the check.
export function isFlowPage(url) {
  try {
    return new URL(url).hostname === 'flow.google.com';
  } catch {
    return false;
  }
}
