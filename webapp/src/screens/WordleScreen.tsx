import { useEffect, useState } from 'react'
import { ApiError, getWordleState, postWordleGuess } from '../lib/api'
import { hapticImpact, hapticResult } from '../lib/telegram'
import { WordleGrid } from '../components/WordleGrid'
import { WordleKeyboard } from '../components/WordleKeyboard'
import { keyboardState } from '../wordleTypes'
import type { WordleState } from '../wordleTypes'

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.message === 'word_not_found') return 'Не знаю такого слова'
    if (e.message === 'game_over') return 'Игра на сегодня окончена'
    if (e.status === 429) return 'Слишком быстро, притормози'
    if (e.status === 401) return 'Открой игру через Telegram-бота'
  }
  return 'Что-то пошло не так, попробуйте ещё раз'
}

export function WordleScreen() {
  const [state, setState] = useState<WordleState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [currentGuess, setCurrentGuess] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [shakeToken, setShakeToken] = useState(0)

  useEffect(() => {
    void loadState()
  }, [])

  async function loadState() {
    try {
      const s = await getWordleState()
      setState(s)
      setLoadError(null)
    } catch (e) {
      setLoadError(errorMessage(e))
    }
  }

  const gameOver = state?.game_over ?? false

  useEffect(() => {
    if (gameOver || busy) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Enter') void handleSubmit()
      else if (e.key === 'Backspace') handleBackspace()
      else if (/^[а-яё]$/i.test(e.key)) handleLetter(e.key.toLowerCase())
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameOver, busy, currentGuess, state])

  function handleLetter(letter: string) {
    if (!state || currentGuess.length >= state.word_length) return
    setCurrentGuess((g) => g + letter)
  }

  function handleBackspace() {
    setCurrentGuess((g) => g.slice(0, -1))
  }

  async function handleSubmit() {
    if (!state || currentGuess.length !== state.word_length) return
    hapticImpact('light')
    setBusy(true)
    setError(null)
    try {
      const result = await postWordleGuess(currentGuess)
      setCurrentGuess('')
      if (result.solved) hapticResult('success')
      else if (result.game_over) hapticResult('error')
      await loadState()
    } catch (e) {
      setError(errorMessage(e))
      setShakeToken((n) => n + 1)
      hapticResult('error')
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-tg-bg px-6 text-center">
        <p className="text-tg-text">{loadError}</p>
        <button
          type="button"
          onClick={() => void loadState()}
          className="rounded-full bg-tg-button px-5 py-2.5 font-medium text-tg-button-text"
        >
          Повторить
        </button>
      </div>
    )
  }

  if (!state) {
    return (
      <div className="flex flex-1 items-center justify-center bg-tg-bg">
        <p className="text-tg-hint">Загрузка…</p>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col bg-tg-bg">
      <div className="border-b border-tg-hint/15 px-4 py-3 text-center">
        <h1 className="text-lg font-semibold text-tg-text">Слово дня #{state.day_no}</h1>
        <p className="text-sm text-tg-hint">
          Попытка {Math.min(state.attempts_count + (gameOver ? 0 : 1), state.max_attempts)} из{' '}
          {state.max_attempts}
          {state.streak > 0 ? ` · Стрик: ${state.streak}🔥` : ''}
        </p>
      </div>

      <div className="flex flex-1 flex-col justify-center overflow-y-auto">
        <div key={shakeToken} className={shakeToken > 0 ? 'animate-shake' : ''}>
          <WordleGrid
            attempts={state.attempts}
            currentGuess={currentGuess}
            wordLength={state.word_length}
            maxAttempts={state.max_attempts}
          />
        </div>
        {error && <p className="px-4 text-center text-sm text-red-500">{error}</p>}
        {gameOver && (
          <p className="px-4 text-center font-medium text-tg-text">
            {state.solved ? '🎉 Угадано!' : `😔 Слово было: ${state.answer?.toUpperCase()}`}
          </p>
        )}
      </div>

      <WordleKeyboard
        letterState={keyboardState(state.attempts)}
        disabled={busy || gameOver}
        onLetter={handleLetter}
        onBackspace={handleBackspace}
        onEnter={() => void handleSubmit()}
      />
    </div>
  )
}
