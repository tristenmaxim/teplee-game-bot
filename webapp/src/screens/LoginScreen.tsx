import { useEffect, useRef, useState } from 'react'
import { postAuthGuest } from '../lib/api'
import { setWebSession } from '../lib/telegram'

interface TelegramAuthUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramAuthUser) => void
  }
}

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME ?? ''
const API_BASE = import.meta.env.VITE_API_URL ?? '/api'

interface Props {
  onLoggedIn: () => void
}

export function LoginScreen({ onLoggedIn }: Props) {
  const widgetRef = useRef<HTMLDivElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    window.onTelegramAuth = async (user: TelegramAuthUser) => {
      setBusy(true)
      setError(null)
      try {
        const res = await fetch(`${API_BASE}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(user),
        })
        if (!res.ok) throw new Error('login failed')
        const body: { init_data: string } = await res.json()
        setWebSession(body.init_data)
        onLoggedIn()
      } catch {
        setError('Не удалось войти, попробуйте ещё раз')
        setBusy(false)
      }
    }

    if (widgetRef.current && BOT_USERNAME) {
      const script = document.createElement('script')
      script.src = 'https://telegram.org/js/telegram-widget.js?22'
      script.async = true
      script.setAttribute('data-telegram-login', BOT_USERNAME)
      script.setAttribute('data-size', 'large')
      script.setAttribute('data-radius', '20')
      script.setAttribute('data-onauth', 'onTelegramAuth(user)')
      script.setAttribute('data-request-access', 'write')
      widgetRef.current.appendChild(script)
    }

    return () => {
      delete window.onTelegramAuth
    }
  }, [onLoggedIn])

  async function handleGuest() {
    setBusy(true)
    setError(null)
    try {
      const res = await postAuthGuest()
      setWebSession(res.init_data)
      onLoggedIn()
    } catch {
      setError('Не удалось войти, попробуйте ещё раз')
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-tg-bg px-6 text-center">
      <p className="text-4xl">🌡️</p>
      <h1 className="text-xl font-semibold text-tg-text">Теплее!</h1>
      <p className="max-w-xs text-tg-hint">
        Войдите через Telegram — прогресс синхронизируется с ботом, играть можно и тут, и там
      </p>
      <div ref={widgetRef} />

      <div className="flex w-full max-w-xs items-center gap-3 text-tg-hint">
        <span className="h-px flex-1 bg-tg-hint/20" />
        <span className="text-xs uppercase">или</span>
        <span className="h-px flex-1 bg-tg-hint/20" />
      </div>

      <button
        type="button"
        onClick={() => void handleGuest()}
        disabled={busy}
        className="rounded-full bg-tg-secondary-bg px-6 py-2.5 font-medium text-tg-text disabled:opacity-50"
      >
        Играть без аккаунта
      </button>
      <p className="max-w-xs text-xs text-tg-hint">
        Без Telegram прогресс останется только в этом браузере — не синхронизируется с ботом
      </p>

      {busy && <p className="text-tg-hint">Входим…</p>}
      {error && <p className="text-red-500">{error}</p>}
      {!BOT_USERNAME && (
        <p className="max-w-xs text-sm text-red-500">
          VITE_BOT_USERNAME не задан — кнопка входа не отрисуется
        </p>
      )}
    </div>
  )
}
