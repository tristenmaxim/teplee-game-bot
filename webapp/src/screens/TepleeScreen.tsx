import { useEffect, useState } from 'react'
import { ApiError, getState, postGuess, postHint, postLang } from '../lib/api'
import { hapticImpact, hapticResult } from '../lib/telegram'
import { Header } from '../components/Header'
import { AttemptsFeed } from '../components/AttemptsFeed'
import { GuessInput } from '../components/GuessInput'
import { WinModal } from '../components/WinModal'
import type { GameState } from '../types'

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.message === 'word_not_found') return 'Не знаю такого слова'
    if (e.message === 'solved') return 'Уже разгадано'
    if (e.status === 429) return 'Слишком быстро, притормози'
    if (e.status === 401) return 'Открой игру через Telegram-бота'
  }
  return 'Что-то пошло не так, попробуйте ещё раз'
}

function hintErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.message === 'no_attempts') return 'Сначала введите хотя бы одно слово'
  }
  return errorMessage(e)
}

export function TepleeScreen() {
  const [gameState, setGameState] = useState<GameState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [guessBusy, setGuessBusy] = useState(false)
  const [guessError, setGuessError] = useState<string | null>(null)
  const [shakeToken, setShakeToken] = useState(0)
  const [langBusy, setLangBusy] = useState(false)
  const [hintBusy, setHintBusy] = useState(false)
  const [lastWord, setLastWord] = useState<string | undefined>()
  const [showWinModal, setShowWinModal] = useState(false)

  useEffect(() => {
    void loadState()
  }, [])

  async function loadState() {
    try {
      const state = await getState()
      setGameState(state)
      setLoadError(null)
    } catch (e) {
      setLoadError(errorMessage(e))
    }
  }

  async function handleGuess(word: string) {
    hapticImpact('light')
    setGuessBusy(true)
    setGuessError(null)
    try {
      const result = await postGuess(word, gameState?.lang)
      setLastWord(result.word)
      if (result.is_win) {
        hapticResult('success')
        setShowWinModal(true)
      } else if (result.rank <= 100) {
        hapticImpact('heavy')
      }
      await loadState()
    } catch (e) {
      setGuessError(errorMessage(e))
      setShakeToken((n) => n + 1)
      hapticResult('error')
    } finally {
      setGuessBusy(false)
    }
  }

  async function handleHint() {
    setHintBusy(true)
    setGuessError(null)
    try {
      const result = await postHint()
      setLastWord(result.word)
      if (result.is_win) {
        hapticResult('success')
        setShowWinModal(true)
      }
      await loadState()
    } catch (e) {
      setGuessError(hintErrorMessage(e))
    } finally {
      setHintBusy(false)
    }
  }

  async function handleToggleLang() {
    if (!gameState) return
    const next = gameState.lang === 'ru' ? 'en' : 'ru'
    setLangBusy(true)
    setLastWord(undefined)
    setShowWinModal(false)
    try {
      await postLang(next)
      await loadState()
    } finally {
      setLangBusy(false)
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

  if (!gameState) {
    return (
      <div className="flex flex-1 items-center justify-center bg-tg-bg">
        <p className="text-tg-hint">Загрузка…</p>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col bg-tg-bg">
      <Header
        dayNo={gameState.day_no}
        lang={gameState.lang}
        attemptsCount={gameState.attempts_count}
        hintsUsed={gameState.hints_used}
        streak={gameState.streak}
        langBusy={langBusy}
        hintBusy={hintBusy}
        hintDisabled={gameState.attempts_count === 0 || gameState.solved}
        onToggleLang={handleToggleLang}
        onHint={handleHint}
      />
      <main className="flex-1 overflow-y-auto">
        <AttemptsFeed attempts={gameState.attempts} lastWord={lastWord} />
      </main>
      <GuessInput
        disabled={guessBusy || hintBusy || gameState.solved}
        shakeToken={shakeToken}
        error={guessError}
        onSubmit={handleGuess}
      />
      {showWinModal && (
        <WinModal
          dayNo={gameState.day_no}
          lang={gameState.lang}
          attempts={gameState.attempts}
          streak={gameState.streak}
          hintsUsed={gameState.hints_used}
          onClose={() => setShowWinModal(false)}
        />
      )}
    </div>
  )
}
