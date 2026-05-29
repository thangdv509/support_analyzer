export interface CriterionScore {
  score: number
  justification: string
}

export interface Criteria {
  greetings: CriterionScore
  grammar: CriterionScore
  communication: CriterionScore
  listening: CriterionScore
  tone_pace: CriterionScore
  empathy: CriterionScore
  enthusiastic: CriterionScore
  probing: CriterionScore
  solution: CriterionScore
  proactiveness: CriterionScore
  transferring: CriterionScore
  resources: CriterionScore
  extra_mile: CriterionScore
  review_asking: CriterionScore
}

export interface Grading {
  criteria: Criteria
  overall_summary?: string
  total_score_20: number
  final_score_10: number
}

export interface QARecord {
  id: string
  uuid?: string
  session_id: string
  date: string
  website_id: string
  app: 'DECO' | 'SearchPie' | string
  customer: string
  primary_operator: string
  is_resolved: boolean
  transcript: string
  summary: string | null
  tags: string[]
  grading: Grading
  crisp_url: string | null
  created_at: string
  updated_at: string
}

export interface RecordsResponse {
  total: number
  page: number
  page_size: number
  records: QARecord[]
  cached_at?: string
}

export interface Stats {
  total: number
  avg_score: number | null
  min_score: number | null
  max_score: number | null
  by_agent: Record<string, { count: number; avg_score: number | null }>
  by_app: Record<string, number>
}

export interface Filters {
  app: string
  agent: string
  date_from: string
  date_to: string
  score_min: number
  score_max: number
  is_resolved: 'all' | 'true' | 'false'
  chat_link: string
}

export const CRITERIA_KEYS = [
  'greetings',
  'grammar',
  'communication',
  'listening',
  'tone_pace',
  'empathy',
  'enthusiastic',
  'probing',
  'solution',
  'proactiveness',
  'transferring',
  'resources',
  'extra_mile',
  'review_asking',
] as const

export type CriterionKey = (typeof CRITERIA_KEYS)[number]

export const CRITERIA_MAX: Record<CriterionKey, number> = {
  greetings: 0.25,
  grammar: 1.25,
  communication: 2.0,
  listening: 1.5,
  tone_pace: 0.75,
  empathy: 0.75,
  enthusiastic: 1.5,
  probing: 1.5,
  solution: 3.0,
  proactiveness: 2.0,
  transferring: 2.0,
  resources: 0.5,
  extra_mile: 1.5,
  review_asking: 1.5,
}

export const CRITERIA_LABELS: Record<CriterionKey, string> = {
  greetings: 'Greetings',
  grammar: 'Grammar',
  communication: 'Communication',
  listening: 'Listening',
  tone_pace: 'Tone/Pace',
  empathy: 'Empathy',
  enthusiastic: 'Enthusiastic',
  probing: 'Probing',
  solution: 'Solution',
  proactiveness: 'Pro-active',
  transferring: 'Transfer',
  resources: 'Resources',
  extra_mile: 'Extra Mile',
  review_asking: 'Ask Review',
}
