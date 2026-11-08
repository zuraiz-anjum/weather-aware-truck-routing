// Times are shown in the browser's own time zone, which is the dispatcher's.

const clock = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

const shortClock = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })

export function formatTime(when: string | Date): string {
  return clock.format(typeof when === 'string' ? new Date(when) : when)
}

export function formatShortTime(when: string | Date): string {
  return shortClock.format(typeof when === 'string' ? new Date(when) : when)
}

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  const hours = Math.floor(minutes / 60)
  if (hours === 0) return `${minutes} min`
  if (minutes % 60 === 0) return `${hours} h`
  return `${hours} h ${minutes % 60} min`
}

export function hoursAfter(departure: string, hours: number): Date {
  return new Date(new Date(departure).getTime() + hours * 3_600_000)
}

// datetime-local inputs speak local wall-clock time without a zone.
export function toInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fromInputValue(value: string): Date | null {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function nextWholeHour(now = new Date()): Date {
  const date = new Date(now)
  date.setMinutes(0, 0, 0)
  date.setHours(date.getHours() + 1)
  return date
}

export function timeZoneName(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}
