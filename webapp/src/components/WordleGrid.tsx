import type { LetterState, WordleAttempt } from '../wordleTypes'

const STATE_BG: Record<LetterState, string> = {
  hit: 'var(--color-rank-hot)',
  present: 'var(--color-rank-warm)',
  miss: 'var(--color-rank-cold)',
}

function Cell({ letter, state }: { letter: string; state?: LetterState }) {
  return (
    <div
      className="flex aspect-square items-center justify-center rounded-lg text-xl font-bold uppercase"
      style={{
        background: state ? STATE_BG[state] : 'var(--tg-secondary-bg)',
        color: state ? 'white' : 'var(--tg-text)',
        border: !state && letter ? '2px solid var(--tg-hint)' : 'none',
      }}
    >
      {letter}
    </div>
  )
}

interface Props {
  attempts: WordleAttempt[]
  currentGuess: string
  wordLength: number
  maxAttempts: number
}

export function WordleGrid({ attempts, currentGuess, wordLength, maxAttempts }: Props) {
  const rows = []
  for (let r = 0; r < maxAttempts; r++) {
    const attempt = attempts[r]
    const isCurrent = !attempt && r === attempts.length
    const letters = attempt
      ? attempt.word.split('')
      : isCurrent
        ? currentGuess.padEnd(wordLength, ' ').split('')
        : Array(wordLength).fill('')
    rows.push(
      <div key={r} className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${wordLength}, 1fr)` }}>
        {letters.map((ch, i) => (
          <Cell key={i} letter={ch.trim()} state={attempt?.feedback[i]} />
        ))}
      </div>,
    )
  }
  return <div className="mx-auto flex w-full max-w-xs flex-col gap-1.5 px-4 py-4">{rows}</div>
}
