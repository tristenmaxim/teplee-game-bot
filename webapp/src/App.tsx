import { useEffect, useState } from 'react'
import { initTelegram } from './lib/telegram'
import { TepleeScreen } from './screens/TepleeScreen'
import { WordleScreen } from './screens/WordleScreen'
import { TimingScreen } from './screens/TimingScreen'

type Tab = 'teplee' | 'wordle' | 'timing'

const TABS: { id: Tab; label: string }[] = [
  { id: 'teplee', label: '🌡️ Теплее!' },
  { id: 'wordle', label: '🔤 Слово дня' },
  { id: 'timing', label: '⏱ Реакция' },
]

function initialTab(): Tab {
  return new URLSearchParams(window.location.search).has('timing_challenge')
    ? 'timing'
    : 'teplee'
}

function App() {
  const [tab, setTab] = useState<Tab>(initialTab)

  useEffect(() => {
    initTelegram()
  }, [])

  return (
    <div className="flex min-h-svh flex-col bg-tg-bg">
      <nav className="flex border-b border-tg-hint/15 bg-tg-header-bg">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className="flex-1 border-b-2 py-2.5 text-sm font-medium"
            style={{
              borderColor: tab === t.id ? 'var(--tg-button)' : 'transparent',
              color: tab === t.id ? 'var(--tg-text)' : 'var(--tg-hint)',
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === 'teplee' && <TepleeScreen />}
      {tab === 'wordle' && <WordleScreen />}
      {tab === 'timing' && <TimingScreen />}
    </div>
  )
}

export default App
