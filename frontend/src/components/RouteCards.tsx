import { levelColor, levelInk, levelName } from '../risk'
import { formatDuration, formatTime } from '../time'
import type { Level, Plan, Route } from '../types'

interface Props {
  plan: Plan
  selected: string | null
  onSelect: (id: string) => void
}

export default function RouteCards({ plan, selected, onSelect }: Props) {
  return (
    <section className="routes" aria-label="Routes">
      {plan.routes.map((route) => (
        <RouteCard key={route.id} route={route} selected={route.id === selected} onSelect={() => onSelect(route.id)} />
      ))}
    </section>
  )
}

function RouteCard({ route, selected, onSelect }: { route: Route; selected: boolean; onSelect: () => void }) {
  const summary = route.summary
  const blocked = summary.miles_by_level[4]
  const bad = summary.miles_by_level[3] + blocked
  return (
    // A click anywhere on the card selects it; the button gives the keyboard the same.
    <article className={selected ? 'route-card selected' : 'route-card'} onClick={onSelect}>
      <h3>
        <button type="button" aria-pressed={selected}>
          Route {route.id}
        </button>{' '}
        <span className="route-name">{route.name}</span>
        {summary.recommended ? (
          <span className="tag">Recommended</span>
        ) : summary.rank === 1 ? (
          <span className="tag danger">Not clear to drive</span>
        ) : (
          <span className="rank">#{summary.rank}</span>
        )}
      </h3>
      <p className="facts">
        {route.distance_miles.toLocaleString(undefined, { maximumFractionDigits: 0 })} mi
        <span className="sep">·</span>
        {formatDuration(route.duration_seconds)}
        <span className="sep">·</span>
        arrives {formatTime(route.arrival)}
      </p>
      <RiskBar miles={summary.miles_by_level} total={route.distance_miles} />
      <p className="facts">
        Worst <b style={{ color: levelInk(summary.worst_level) }}>{levelName(summary.worst_level)}</b>
        <span className="sep">·</span>
        Average {summary.average_risk.toFixed(2)}
        {bad > 0 && (
          <>
            <span className="sep">·</span>
            <span style={{ color: levelInk(blocked > 0 ? 4 : 3) }}>
              {bad.toLocaleString(undefined, { maximumFractionDigits: 0 })} mi Severe or worse
              {blocked > 0 && `, ${blocked.toLocaleString(undefined, { maximumFractionDigits: 0 })} of them No Travel`}
            </span>
          </>
        )}
      </p>
      {summary.reason && <p className="reason">{summary.reason[0].toUpperCase() + summary.reason.slice(1)}.</p>}
      {route.detour && <p className="small muted">Found by routing through a point to one side of the direct line.</p>}
    </article>
  )
}

function RiskBar({ miles, total }: { miles: number[]; total: number }) {
  const parts = miles
    .map((m, level) => ({ m, level: level as Level }))
    .filter(({ m }) => m > 0)
  const words = parts.map(({ m, level }) => `${Math.round(m)} mi ${levelName(level)}`).join(', ')
  return (
    <div className="risk-bar" role="img" aria-label={words}>
      {parts.map(({ m, level }) => (
        <span key={level} style={{ width: `${(m / total) * 100}%`, background: levelColor(level) }} title={`${Math.round(m)} mi ${levelName(level)}`} />
      ))}
    </div>
  )
}
