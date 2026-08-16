export type TimingMode = 'visible' | 'hidden'

export interface TimingStartResponse {
  round_id: string
  target_ms: number
  mode: TimingMode
}

export interface TimingStopResponse {
  elapsed_ms: number
  target_ms: number
  delta_ms: number
  rating: string
}

export interface TimingChallengeResponse {
  id: string
  mode: TimingMode
  link: string
}

export interface TimingResult {
  label: string
  elapsed_ms: number
  delta_ms: number
}

export interface TimingChallengeInfo {
  mode: TimingMode
  results: TimingResult[]
}

export function formatSeconds(ms: number): string {
  return (ms / 1000).toFixed(2)
}
