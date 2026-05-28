import axios from 'axios'
import type { QARecord, RecordsResponse, Stats } from './types'

const http = axios.create({ baseURL: '/api' })

export interface ListParams {
  app?: string
  agent?: string
  date_from?: string
  date_to?: string
  score_min?: number
  score_max?: number
  is_resolved?: boolean
  page?: number
  page_size?: number
  sort_by?: string
  sort_dir?: number
}

export async function fetchRecords(params: ListParams): Promise<RecordsResponse> {
  const { data } = await http.get('/records', { params })
  return data
}

export async function fetchRecord(id: string): Promise<QARecord> {
  const { data } = await http.get(`/records/${id}`)
  return data
}

export async function updateRecord(
  id: string,
  updates: Partial<Pick<QARecord, 'customer' | 'primary_operator' | 'is_resolved' | 'summary' | 'tags' | 'grading'>>,
): Promise<QARecord> {
  const { data } = await http.put(`/records/${id}`, updates)
  return data
}

export async function deleteRecord(id: string): Promise<void> {
  await http.delete(`/records/${id}`)
}

export async function regradeRecord(id: string, feedback?: string): Promise<QARecord> {
  const { data } = await http.post(`/records/${id}/regrade`, {
    feedback: feedback || null,
  })
  return data
}

export async function resolveRecord(id: string): Promise<{ ok: boolean; record: QARecord }> {
  const { data } = await http.post(`/records/${id}/resolve`)
  return data
}

export async function fetchAgents(app?: string): Promise<string[]> {
  const { data } = await http.get('/agents', { params: { app: app || '' } })
  return data
}

export async function fetchStats(params: {
  app?: string
  date_from?: string
  date_to?: string
}): Promise<Stats> {
  const { data } = await http.get('/stats', { params })
  return data
}
