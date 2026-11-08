import { levelColor, levelName } from '../risk'
import { formatShortTime } from '../time'
import type { Level, Route } from '../types'

function tone(level: Level) {
  return level > 0 ? { color: levelColor(level), fontWeight: 600 } : undefined
}

export default function CheckpointTable({ route }: { route: Route }) {
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
            <tr key={c.mile}>
              <td className="num">{Math.round(c.mile)}</td>
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
                <span className="chip" style={{ background: levelColor(c.level) }}>
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
