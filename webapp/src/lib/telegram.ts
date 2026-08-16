// Telegram Mini App bridge (TECH_SPEC §7). Uses window.Telegram.WebApp from
// the official telegram-web-app.js script (loaded in index.html).

interface TelegramWebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  ready: () => void
  expand: () => void
  onEvent: (event: 'themeChanged', cb: () => void) => void
  openTelegramLink: (url: string) => void
  HapticFeedback: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy') => void
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp }
  }
}

function getWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp
}

const THEME_VARS: Record<string, string> = {
  bg_color: '--tg-bg',
  text_color: '--tg-text',
  hint_color: '--tg-hint',
  link_color: '--tg-link',
  button_color: '--tg-button',
  button_text_color: '--tg-button-text',
  secondary_bg_color: '--tg-secondary-bg',
  header_bg_color: '--tg-header-bg',
  section_bg_color: '--tg-section-bg',
}

function applyTheme(wa: TelegramWebApp): void {
  const root = document.documentElement
  for (const [key, cssVar] of Object.entries(THEME_VARS)) {
    const value = wa.themeParams[key]
    if (value) root.style.setProperty(cssVar, value)
  }
}

export function initTelegram(): void {
  const wa = getWebApp()
  if (!wa) return
  wa.ready()
  wa.expand()
  applyTheme(wa)
  wa.onEvent('themeChanged', () => applyTheme(wa))
}

// Outside Telegram (plain browser dev) initData is empty and the API will
// reject it; VITE_DEV_INIT_DATA lets a dev paste a signed fixture locally.
// See webapp/.env.example for how to generate one.
export function getInitData(): string {
  const wa = getWebApp()
  if (wa?.initData) return wa.initData
  return import.meta.env.VITE_DEV_INIT_DATA ?? ''
}

export function hapticImpact(style: 'light' | 'medium' | 'heavy'): void {
  getWebApp()?.HapticFeedback.impactOccurred(style)
}

export function hapticResult(kind: 'success' | 'error'): void {
  getWebApp()?.HapticFeedback.notificationOccurred(kind)
}

export function openShareLink(url: string): void {
  const wa = getWebApp()
  if (wa) wa.openTelegramLink(url)
  else window.open(url, '_blank')
}
