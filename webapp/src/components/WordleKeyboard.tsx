import { RU_KEYBOARD_ROWS, type LetterState } from '../wordleTypes'

const STATE_BG: Record<LetterState, string> = {
  hit: 'var(--color-rank-hot)',
  present: 'var(--color-rank-warm)',
  miss: 'var(--color-rank-cold)',
}

interface Props {
  letterState: Record<string, LetterState>
  disabled: boolean
  onLetter: (letter: string) => void
  onBackspace: () => void
  onEnter: () => void
}

export function WordleKeyboard({ letterState, disabled, onLetter, onBackspace, onEnter }: Props) {
  return (
    <div className="flex flex-col gap-1.5 px-2 pb-3">
      {RU_KEYBOARD_ROWS.map((row, i) => (
        <div key={i} className="flex justify-center gap-1">
          {row.map((letter) => {
            const state = letterState[letter]
            return (
              <button
                key={letter}
                type="button"
                disabled={disabled}
                onClick={() => onLetter(letter)}
                className="h-11 flex-1 max-w-9 rounded-md text-sm font-semibold uppercase disabled:opacity-50"
                style={{
                  background: state ? STATE_BG[state] : 'var(--tg-secondary-bg)',
                  color: state ? 'white' : 'var(--tg-text)',
                }}
              >
                {letter}
              </button>
            )
          })}
        </div>
      ))}
      <div className="flex justify-center gap-1">
        <button
          type="button"
          disabled={disabled}
          onClick={onBackspace}
          className="h-11 flex-[1.5] rounded-md bg-tg-secondary-bg text-sm font-semibold text-tg-text disabled:opacity-50"
        >
          ⌫
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onEnter}
          className="h-11 flex-[1.5] rounded-md bg-tg-button text-sm font-semibold text-tg-button-text disabled:opacity-50"
        >
          Ввод
        </button>
      </div>
    </div>
  )
}
