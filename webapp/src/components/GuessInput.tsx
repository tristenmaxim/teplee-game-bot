import { useState, type FormEvent } from 'react'

interface Props {
  disabled: boolean
  shakeToken: number
  error: string | null
  onSubmit: (word: string) => void
}

export function GuessInput({ disabled, shakeToken, error, onSubmit }: Props) {
  const [value, setValue] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const word = value.trim()
    if (!word || disabled) return
    onSubmit(word)
    setValue('')
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="sticky bottom-0 border-t border-tg-hint/15 bg-tg-header-bg px-4 py-3"
    >
      {error && <p className="mb-2 text-sm text-red-500">{error}</p>}
      <div key={shakeToken} className={`flex gap-2 ${shakeToken > 0 ? 'animate-shake' : ''}`}>
        <input
          type="text"
          name="guess"
          id="guess"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled}
          placeholder="Введите слово…"
          autoComplete="off"
          autoCapitalize="off"
          className="min-w-0 flex-1 rounded-full bg-tg-secondary-bg px-4 py-2.5 text-tg-text outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="shrink-0 rounded-full bg-tg-button px-5 py-2.5 font-medium text-tg-button-text disabled:opacity-50"
        >
          →
        </button>
      </div>
    </form>
  )
}
