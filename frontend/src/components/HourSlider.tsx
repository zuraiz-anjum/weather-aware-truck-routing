import { useEffect, useRef, useState } from 'react'
import { formatTime, hoursAfter } from '../time'
import type { Plan } from '../types'

interface Props {
  plan: Plan
  hour: number
  onChange: (hour: number) => void
}

const STEP_MS = 400

export default function HourSlider({ plan, hour, onChange }: Props) {
  // Playing is tied to the plan it was started on, so a new plan starts still.
  const [playingPlan, setPlayingPlan] = useState<Plan | null>(null)
  const playing = playingPlan === plan
  const latest = useRef(hour)

  useEffect(() => {
    latest.current = hour
  }, [hour])

  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => onChange(latest.current >= plan.slider_hours ? 0 : latest.current + 1), STEP_MS)
    return () => clearInterval(timer)
  }, [playing, plan.slider_hours, onChange])

  return (
    <div className="hour-slider">
      <button type="button" onClick={() => setPlayingPlan(playing ? null : plan)} aria-pressed={playing}>
        {playing ? 'Pause' : 'Play'}
      </button>
      <div className="hour-slider-body">
        <label htmlFor="hour">
          Forecast at <b>{formatTime(hoursAfter(plan.departure, hour))}</b>
          <span className="muted"> (departure + {hour} h)</span>
        </label>
        <input
          id="hour"
          type="range"
          min={0}
          max={plan.slider_hours}
          step={1}
          value={hour}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </div>
    </div>
  )
}
