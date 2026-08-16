import type { Lang } from '../types'

const LANG_FLAG: Record<Lang, string> = { ru: '🇷🇺', en: '🇺🇸' }

interface Props {
  dayNo?: number
  lang: Lang
  attemptsCount: number
  hintsUsed: number
  streak: number
  langBusy: boolean
  hintBusy: boolean
  hintDisabled: boolean
  onToggleLang: () => void
  onHint: () => void
}

export function Header({
  dayNo,
  lang,
  attemptsCount,
  hintsUsed,
  streak,
  langBusy,
  hintBusy,
  hintDisabled,
  onToggleLang,
  onHint,
}: Props) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-tg-hint/15 bg-tg-header-bg px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-tg-text">
          Теплее! {dayNo != null ? `#${dayNo}` : ''}
        </h1>
        <p className="text-sm text-tg-hint">
          Попыток: {attemptsCount}
          {hintsUsed > 0 ? ` · Подсказок: ${hintsUsed}` : ''}
          {streak > 0 ? ` · Стрик: ${streak}🔥` : ''}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onHint}
          disabled={hintBusy || hintDisabled}
          className="rounded-full bg-tg-secondary-bg px-3 py-2 text-xl leading-none disabled:opacity-50"
          aria-label="Подсказка"
        >
          💡
        </button>
        <button
          type="button"
          onClick={onToggleLang}
          disabled={langBusy}
          className="rounded-full bg-tg-secondary-bg px-3 py-2 text-xl leading-none disabled:opacity-50"
          aria-label="Сменить язык слова дня"
        >
          {LANG_FLAG[lang]}
        </button>
      </div>
    </header>
  )
}
