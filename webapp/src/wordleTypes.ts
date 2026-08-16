export type LetterState = 'hit' | 'present' | 'miss'

export interface WordleAttempt {
  word: string
  feedback: LetterState[]
}

export interface WordleState {
  game_key: string
  day_no: number
  attempts: WordleAttempt[]
  attempts_count: number
  solved: boolean
  game_over: boolean
  streak: number
  word_length: number
  max_attempts: number
  answer: string | null
}

export interface WordleGuessResponse {
  attempts: WordleAttempt[]
  solved: boolean
  game_over: boolean
  streak: number
}

export const RU_KEYBOARD_ROWS: string[][] = [
  ['й', 'ц', 'у', 'к', 'е', 'н', 'г', 'ш', 'щ', 'з', 'х', 'ъ'],
  ['ф', 'ы', 'в', 'а', 'п', 'р', 'о', 'л', 'д', 'ж', 'э'],
  ['я', 'ч', 'с', 'м', 'и', 'т', 'ь', 'б', 'ю'],
]

// Best state a letter has ever reached across all guesses (hit beats present beats miss).
export function keyboardState(attempts: WordleAttempt[]): Record<string, LetterState> {
  const best: Record<string, LetterState> = {}
  const rank: Record<LetterState, number> = { miss: 0, present: 1, hit: 2 }
  for (const attempt of attempts) {
    for (let i = 0; i < attempt.word.length; i++) {
      const letter = attempt.word[i]
      const state = attempt.feedback[i]
      if (!best[letter] || rank[state] > rank[best[letter]]) {
        best[letter] = state
      }
    }
  }
  return best
}
