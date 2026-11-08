import { LEVELS, levelColor, levelName } from '../risk'

export default function Legend({ cellMiles }: { cellMiles: number }) {
  return (
    <div className="legend">
      <ul aria-label="Risk levels">
        {LEVELS.map((level) => (
          <li key={level}>
            <span className="swatch" style={{ background: levelColor(level) }} />
            {levelName(level)}
          </li>
        ))}
      </ul>
      <p className="small muted">
        Cells {Math.round(cellMiles)} mi across, rated at the slider hour; dots are checkpoints, rated when the truck gets there.
      </p>
    </div>
  )
}
