import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { suggestPlaces } from '../api'
import type { Place } from '../types'

export interface PlaceValue {
  text: string
  place?: Place
}

interface Props {
  label: string
  value: PlaceValue
  onChange: (value: PlaceValue) => void
  placeholder?: string
}

const TYPING_PAUSE_MS = 250

export default function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const id = useId()
  const [options, setOptions] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [failed, setFailed] = useState(false)
  const pending = useRef<AbortController | null>(null)
  const focused = useRef(false)

  const wanted = !value.place && value.text.trim().length >= 2

  useEffect(() => {
    // Ask a moment after typing stops. A picked place needs no suggestions.
    if (!wanted) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      pending.current?.abort()
      pending.current = controller
      suggestPlaces(value.text, controller.signal)
        .then((found) => {
          setOptions(found)
          setActive(-1)
          // By the time the answer comes the user may have moved on to the next field.
          setOpen(focused.current)
          setFailed(false)
        })
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === 'AbortError')) setFailed(true)
        })
    }, TYPING_PAUSE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [wanted, value.text])

  function pick(place: Place) {
    onChange({ text: place.label, place })
    setOpen(false)
    setOptions([])
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!open || options.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((a) => (a + 1) % options.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((a) => (a - 1 + options.length) % options.length)
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault()
      pick(options[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  const listId = `${id}-list`
  const showing = wanted && open && options.length > 0

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showing}
        aria-controls={listId}
        aria-activedescendant={showing && active >= 0 ? `${id}-option-${active}` : undefined}
        autoComplete="off"
        spellCheck={false}
        maxLength={200} // as much as the server reads of a name
        placeholder={placeholder}
        value={value.text}
        onChange={(event) => onChange({ text: event.target.value })}
        onFocus={() => {
          focused.current = true
          if (options.length > 0) setOpen(true)
        }}
        onBlur={() => {
          focused.current = false
          setOpen(false)
        }}
        onKeyDown={onKeyDown}
      />
      {showing && (
        <ul id={listId} role="listbox" className="suggestions">
          {options.map((place, index) => (
            <li
              key={place.label}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={index === active}
              className={index === active ? 'active' : undefined}
              onPointerDown={(event) => {
                // Pointer rather than mouse: a finger fires it too, and before the
                // input loses focus, so blur does not close the list first.
                event.preventDefault()
                pick(place)
              }}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
      <small className="hint">
        {value.place
          ? `${value.place.lat.toFixed(3)}, ${value.place.lon.toFixed(3)}`
          : failed
            ? 'Suggestions are not available; the name will be looked up when you plan.'
            : ' '}
      </small>
    </div>
  )
}
