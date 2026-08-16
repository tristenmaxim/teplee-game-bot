import { closeness, rankColorVar, rankEmoji, type Attempt } from '../types'

function AttemptRow({ attempt, highlighted }: { attempt: Attempt; highlighted: boolean }) {
  const fillPct = Math.round(closeness(attempt.rank) * 100)
  return (
    <li
      className={`relative flex items-center justify-between overflow-hidden rounded-lg border px-3 py-2 transition-colors ${
        highlighted ? 'border-tg-link' : 'border-transparent'
      }`}
      style={{ background: 'var(--tg-secondary-bg)' }}
    >
      <div
        className="absolute inset-y-0 left-0 opacity-25"
        style={{ width: `${fillPct}%`, background: rankColorVar(attempt.rank) }}
      />
      <span className="relative flex items-center gap-2 font-medium text-tg-text">
        <span>{rankEmoji(attempt.rank)}</span>
        <span>{attempt.word}</span>
      </span>
      <span className="relative text-sm text-tg-hint">{attempt.rank}</span>
    </li>
  )
}

interface Props {
  attempts: Attempt[]
  lastWord?: string
}

export function AttemptsFeed({ attempts, lastWord }: Props) {
  const last = lastWord ? attempts.find((a) => a.word === lastWord) : undefined

  if (attempts.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-tg-hint">
        Пока ни одной попытки — введите первое слово ниже
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {last && (
        <div>
          <p className="mb-1 text-xs uppercase tracking-wide text-tg-hint">последнее</p>
          <ul>
            <AttemptRow attempt={last} highlighted />
          </ul>
        </div>
      )}
      <ul className="flex flex-col gap-1.5">
        {attempts.map((a) => (
          <AttemptRow key={a.word} attempt={a} highlighted={a.word === lastWord} />
        ))}
      </ul>
    </div>
  )
}
