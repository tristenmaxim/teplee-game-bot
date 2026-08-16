export type Lang = 'ru' | 'en'

export interface Attempt {
  word: string
  rank: number
}

export interface GameState {
  game_key: string
  lang: Lang
  day_no?: number
  attempts: Attempt[]
  attempts_count: number
  hints_used: number
  solved: boolean
  streak: number
}

export interface GuessResponse {
  word: string
  rank: number
  is_new: boolean
  is_win: boolean
  attempts_count: number
  streak: number
  hints_used: number
}

const MAX_RANK = 30000

export function rankEmoji(rank: number): string {
  if (rank <= 100) return '🟩'
  if (rank <= 1000) return '🟨'
  return '⬜'
}

export function rankColorVar(rank: number): string {
  if (rank <= 100) return 'var(--color-rank-hot)'
  if (rank <= 1000) return 'var(--color-rank-warm)'
  return 'var(--color-rank-cold)'
}

// Log-scale closeness fill for the progress bar inside each rank pill —
// ranks span 1..~30000, a linear scale would make everything past rank 500
// look identically empty.
export function closeness(rank: number): number {
  const clamped = Math.min(Math.max(rank, 1), MAX_RANK)
  return 1 - Math.log(clamped) / Math.log(MAX_RANK)
}

// Share-text emoji bar (PRD §5C). Attempts can run into the dozens, so each
// bucket is capped rather than rendered 1:1 — a decorative summary, not a grid.
export function shareBar(attempts: Attempt[]): string {
  const hot = attempts.filter((a) => a.rank <= 100).length
  const warm = attempts.filter((a) => a.rank > 100 && a.rank <= 1000).length
  const cold = attempts.length - hot - warm
  const cap = (n: number) => Math.min(n, 5)
  return '🟩'.repeat(cap(hot)) + '🟨'.repeat(cap(warm)) + '⬜'.repeat(cap(cold))
}
