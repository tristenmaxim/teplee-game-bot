import { useEffect, useState } from 'react'
import { initTelegram } from './lib/telegram'
import { TepleeScreen } from './screens/TepleeScreen'
import { WordleScreen } from './screens/WordleScreen'

type Tab = 'teplee' | 'wordle'

function App() {
  const [tab, setTab] = useState<Tab>('teplee')

  useEffect(() => {
    initTelegram()
  }, [])

  return (
    <div className="flex min-h-svh flex-col bg-tg-bg">
      <nav className="flex border-b border-tg-hint/15 bg-tg-header-bg">
        <button
          type="button"
          onClick={() => setTab('teplee')}
          className="flex-1 border-b-2 py-2.5 text-sm font-medium"
          style={{
            borderColor: tab === 'teplee' ? 'var(--tg-button)' : 'transparent',
            color: tab === 'teplee' ? 'var(--tg-text)' : 'var(--tg-hint)',
          }}
        >
          🌡️ Теплее!
        </button>
        <button
          type="button"
          onClick={() => setTab('wordle')}
          className="flex-1 border-b-2 py-2.5 text-sm font-medium"
          style={{
            borderColor: tab === 'wordle' ? 'var(--tg-button)' : 'transparent',
            color: tab === 'wordle' ? 'var(--tg-text)' : 'var(--tg-hint)',
          }}
        >
          🔤 Слово дня
        </button>
      </nav>
      {tab === 'teplee' ? <TepleeScreen /> : <WordleScreen />}
    </div>
  )
}

export default App
