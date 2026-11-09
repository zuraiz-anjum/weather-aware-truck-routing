// The API speaks in lower case without a full stop, so that its messages
// can be joined; shown on their own they are made sentences.
export function sentence(text: string): string {
  const trimmed = text.trim()
  if (!trimmed) return trimmed
  return trimmed[0].toUpperCase() + trimmed.slice(1) + (/[.!?]$/.test(trimmed) ? '' : '.')
}
