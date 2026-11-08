import { LEVELS, levelColor, levelName } from '../risk'

export default function Legend() {
  return (
    <ul className="legend" aria-label="Risk levels">
      {LEVELS.map((level) => (
        <li key={level}>
          <span className="swatch" style={{ background: levelColor(level) }} />
          {levelName(level)}
        </li>
      ))}
    </ul>
  )
}
