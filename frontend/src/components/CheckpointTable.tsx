import { chipText, levelColor, levelInk, levelName } from '../risk'
import { formatShortTime } from '../time'
import type { Checkpoint, Level, Route } from '../types'

interface Props {
  route: Route
  picked?: number | null // the mile of the checkpoint the map has been taken to
  onPick?: (checkpoint: Checkpoint) => void
}

function tone(level: Level) {
  return level > 0 ? { color: levelInk(level), fontWeight: 600 } : undefined
}

export default function CheckpointTable({ route, picked = null, onPick }: Props) {
  return (
    <section className="checkpoints" aria-label={`Checkpoints on route ${route.id}`}>
      <h3>
        Route {route.id} checkpoints <span className="muted">at the truck's time of arrival</span>
      </h3>
      <table>
        <thead>
          <tr>
            <th className="num">Mile</th>
            <th>ETA</th>
            <th className="num">
              Wind <small>mph</small>
            </th>
            <th className="num">
              Rain <small>in/h</small>
            </th>
            <th className="num">
              Snow <small>in/h</small>
            </th>
            <th>Risk</th>
          </tr>
        </thead>
        <tbody>
          {route.checkpoints.map((c) => (
            // A click anywhere on the row takes the map there; the mile is a button so the keyboard can do the same.
            <tr key={c.mile} className={c.mile === picked ? 'picked' : undefined} onClick={() => onPick?.(c)}>
              <td className="num">
                <button type="button" className="link" title="Show on the map">
                  {Math.round(c.mile)}
                </button>
              </td>
              <td>{formatShortTime(c.eta)}</td>
              <td className="num" style={tone(c.wind_level)}>
                {c.wind_mph.toFixed(0)}
              </td>
              <td className="num" style={tone(c.rain_level)}>
                {c.rain_in.toFixed(2)}
              </td>
              <td className="num" style={tone(c.snow_level)}>
                {c.snow_in.toFixed(2)}
              </td>
              <td>
                <span className="chip" style={{ background: levelColor(c.level), color: chipText(c.level) }}>
                  {levelName(c.level)}
                </span>
                {c.load_rule && (
                  <small className="muted" title={c.load_rule}>
                    {' '}
                    load rule
                  </small>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
