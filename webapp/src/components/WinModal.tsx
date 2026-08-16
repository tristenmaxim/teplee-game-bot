import { useEffect } from 'react'
import confetti from 'canvas-confetti'
import { openShareLink } from '../lib/telegram'
import { shareBar, type Attempt, type Lang } from '../types'

const LANG_FLAG: Record<Lang, string> = { ru: '🇷🇺', en: '🇺🇸' }
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME ?? ''

interface Props {
  dayNo?: number
  lang: Lang
  attempts: Attempt[]
  streak: number
  onClose: () => void
}

export function WinModal({ dayNo, lang, attempts, streak, onClose }: Props) {
  useEffect(() => {
    confetti({ particleCount: 120, spread: 80, origin: { y: 0.6 } })
  }, [])

  function handleShare() {
    const bar = shareBar(attempts)
    const text =
      `Теплее! ${dayNo != null ? `#${dayNo} ` : ''}${LANG_FLAG[lang]} | ` +
      `Попыток: ${attempts.length} | ${bar} | Стрик: ${streak}🔥`
    const botUrl = BOT_USERNAME ? `https://t.me/${BOT_USERNAME}` : 'https://t.me'
    const link = `https://t.me/share/url?url=${encodeURIComponent(botUrl)}&text=${encodeURIComponent(text)}`
    openShareLink(link)
  }

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 sm:items-center">
      <div className="w-full max-w-sm rounded-t-2xl bg-tg-section-bg p-6 text-center sm:rounded-2xl">
        <p className="text-4xl">🎉</p>
        <h2 className="mt-2 text-xl font-semibold text-tg-text">Угадано!</h2>
        <p className="mt-1 text-tg-hint">
          {dayNo != null ? `День #${dayNo} ${LANG_FLAG[lang]}` : LANG_FLAG[lang]} · Попыток:{' '}
          {attempts.length}
        </p>
        <p className="mt-2 text-lg">{shareBar(attempts)}</p>
        {streak > 0 && <p className="mt-2 font-medium text-tg-text">Стрик: {streak}🔥</p>}

        <div className="mt-6 flex flex-col gap-2">
          <button
            type="button"
            onClick={handleShare}
            className="rounded-full bg-tg-button px-5 py-2.5 font-medium text-tg-button-text"
          >
            Поделиться
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full bg-tg-secondary-bg px-5 py-2.5 font-medium text-tg-text"
          >
            Дорешивать
          </button>
        </div>
      </div>
    </div>
  )
}
