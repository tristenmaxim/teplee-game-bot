import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  getTimingChallenge,
  postTimingChallenge,
  postTimingStart,
  postTimingStop,
} from '../lib/api'
import { hapticImpact, hapticResult, openShareLink } from '../lib/telegram'
import { formatSeconds, type TimingChallengeInfo, type TimingMode, type TimingStopResponse } from '../timingTypes'

type Phase = 'idle' | 'running' | 'result'

function challengeIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('timing_challenge')
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.message === 'already_played') return 'Ты уже играл в этом вызове'
    if (e.status === 401) return 'Открой игру через Telegram-бота'
  }
  return 'Что-то пошло не так, попробуйте ещё раз'
}

export function TimingScreen() {
  const challengeId = useRef(challengeIdFromUrl()).current
  const [mode, setMode] = useState<TimingMode>('visible')
  const [challengeInfo, setChallengeInfo] = useState<TimingChallengeInfo | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [roundId, setRoundId] = useState<string | null>(null)
  const [elapsedDisplay, setElapsedDisplay] = useState(0)
  const [result, setResult] = useState<TimingStopResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [shareLink, setShareLink] = useState<string | null>(null)
  const startedAtRef = useRef(0)
  const rafRef = useRef(0)

  useEffect(() => {
    if (challengeId) {
      getTimingChallenge(challengeId)
        .then(setChallengeInfo)
        .catch((e) => setError(errorMessage(e)))
    }
  }, [challengeId])

  useEffect(() => () => cancelAnimationFrame(rafRef.current), [])

  const effectiveMode = challengeInfo?.mode ?? mode

  async function handleStart() {
    setError(null)
    setBusy(true)
    try {
      const started = await postTimingStart(mode, challengeId ?? undefined)
      setRoundId(started.round_id)
      setPhase('running')
      startedAtRef.current = performance.now()
      if (started.mode === 'visible') tick()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  function tick() {
    setElapsedDisplay(performance.now() - startedAtRef.current)
    rafRef.current = requestAnimationFrame(tick)
  }

  async function handleStop() {
    if (!roundId) return
    cancelAnimationFrame(rafRef.current)
    hapticImpact('light')
    setBusy(true)
    try {
      const res = await postTimingStop(roundId)
      setResult(res)
      setPhase('result')
      hapticResult(res.delta_ms <= 200 ? 'success' : 'error')
      if (challengeId) {
        getTimingChallenge(challengeId).then(setChallengeInfo).catch(() => {})
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleCreateChallenge() {
    setBusy(true)
    setError(null)
    try {
      const res = await postTimingChallenge(mode)
      setShareLink(res.link)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  function handleShare() {
    if (!shareLink) return
    const text = 'Кто точнее остановит время? ⏱ Прими вызов!'
    const url = `https://t.me/share/url?url=${encodeURIComponent(shareLink)}&text=${encodeURIComponent(text)}`
    openShareLink(url)
  }

  function reset() {
    setPhase('idle')
    setRoundId(null)
    setResult(null)
    setElapsedDisplay(0)
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-tg-bg px-6 py-8 text-center">
      {challengeId && (
        <p className="text-sm text-tg-hint">
          ⚔️ Вызов на точность {challengeInfo ? `· режим: ${challengeInfo.mode === 'hidden' ? 'вслепую' : 'открытый'}` : ''}
        </p>
      )}

      {phase === 'idle' && (
        <>
          {!challengeId && (
            <div className="flex gap-2 rounded-full bg-tg-secondary-bg p-1">
              <button
                type="button"
                onClick={() => setMode('visible')}
                className="rounded-full px-4 py-2 text-sm font-medium"
                style={{
                  background: mode === 'visible' ? 'var(--tg-button)' : 'transparent',
                  color: mode === 'visible' ? 'var(--tg-button-text)' : 'var(--tg-text)',
                }}
              >
                Открытый таймер
              </button>
              <button
                type="button"
                onClick={() => setMode('hidden')}
                className="rounded-full px-4 py-2 text-sm font-medium"
                style={{
                  background: mode === 'hidden' ? 'var(--tg-button)' : 'transparent',
                  color: mode === 'hidden' ? 'var(--tg-button-text)' : 'var(--tg-text)',
                }}
              >
                Вслепую
              </button>
            </div>
          )}
          <p className="text-tg-hint">
            Жми «Старт», затем «Стоп» как можно точнее в загаданный момент — сколько секунд
            пройдёт, узнаешь только после старта.
          </p>
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={busy}
            className="rounded-full bg-tg-button px-8 py-3 text-lg font-semibold text-tg-button-text disabled:opacity-50"
          >
            ▶️ Старт
          </button>
          {!challengeId && (
            <button
              type="button"
              onClick={() => void handleCreateChallenge()}
              disabled={busy}
              className="text-sm text-tg-link underline"
            >
              ⚔️ Вызвать друга
            </button>
          )}
          {shareLink && (
            <button
              type="button"
              onClick={handleShare}
              className="rounded-full bg-tg-secondary-bg px-5 py-2.5 text-sm font-medium text-tg-text"
            >
              📤 Поделиться вызовом
            </button>
          )}
        </>
      )}

      {phase === 'running' && (
        <>
          <p className="text-tg-hint">Останови точно в загаданный момент</p>
          <p className="text-5xl font-bold tabular-nums text-tg-text">
            {effectiveMode === 'visible' ? formatSeconds(elapsedDisplay) : '⏳'}
          </p>
          <button
            type="button"
            onClick={() => void handleStop()}
            disabled={busy}
            className="rounded-full bg-tg-button px-8 py-3 text-lg font-semibold text-tg-button-text disabled:opacity-50"
          >
            ⏹ Стоп
          </button>
        </>
      )}

      {phase === 'result' && result && (
        <>
          <p className="text-2xl font-bold text-tg-text">{result.rating}</p>
          <p className="text-tg-hint">
            Загадано: {formatSeconds(result.target_ms)} с · Твоё время:{' '}
            {formatSeconds(result.elapsed_ms)} с
          </p>
          <p className="text-lg font-semibold text-tg-text">
            Погрешность: {formatSeconds(result.delta_ms)} с
          </p>

          {challengeId && challengeInfo && (
            <div className="w-full max-w-xs rounded-lg bg-tg-secondary-bg p-3">
              <p className="mb-2 text-xs uppercase tracking-wide text-tg-hint">Таблица вызова</p>
              {challengeInfo.results.map((r, i) => (
                <div key={i} className="flex justify-between py-1 text-sm text-tg-text">
                  <span>
                    {i + 1}. {r.label}
                  </span>
                  <span>{formatSeconds(r.delta_ms)} с</span>
                </div>
              ))}
            </div>
          )}

          {!challengeId && (
            <button
              type="button"
              onClick={reset}
              className="rounded-full bg-tg-button px-6 py-2.5 font-medium text-tg-button-text"
            >
              Ещё раз
            </button>
          )}
        </>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  )
}
