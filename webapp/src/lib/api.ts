import { getInitData } from './telegram'
import type { GameState, GuessResponse, Lang } from '../types'
import type { WordleGuessResponse, WordleState } from '../wordleTypes'

const API_BASE = import.meta.env.VITE_API_URL ?? '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `tma ${getInitData()}`,
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const body: { detail?: string } = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export function getState(): Promise<GameState> {
  return request<GameState>('/state?game_param=d')
}

export function postGuess(word: string, lang?: Lang): Promise<GuessResponse> {
  return request<GuessResponse>('/guess', {
    method: 'POST',
    body: JSON.stringify({ game: 'd', word, lang }),
  })
}

export function postHint(): Promise<GuessResponse> {
  return request<GuessResponse>('/hint', {
    method: 'POST',
    body: JSON.stringify({ game: 'd' }),
  })
}

export function postLang(lang: Lang): Promise<{ lang: Lang }> {
  return request<{ lang: Lang }>('/lang', {
    method: 'POST',
    body: JSON.stringify({ lang }),
  })
}

export function getWordleState(): Promise<WordleState> {
  return request<WordleState>('/wordle/state')
}

export function postWordleGuess(word: string): Promise<WordleGuessResponse> {
  return request<WordleGuessResponse>('/wordle/guess', {
    method: 'POST',
    body: JSON.stringify({ word }),
  })
}
