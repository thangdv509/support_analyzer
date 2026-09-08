import axios from 'axios'
import type { Role } from '@/features/auth/api'

export type { Role }

export interface UserRecord {
  email: string
  name: string
  picture: string
  role: Role
  added_by: string
  created_at: string
  last_login?: string
}

const http = axios.create({ baseURL: '/api', withCredentials: true })

export async function fetchUsers(): Promise<UserRecord[]> {
  const { data } = await http.get('/users')
  return data
}

export async function addUser(email: string, role: Role): Promise<void> {
  await http.post('/users', { email, role })
}

export async function updateRole(email: string, role: Role): Promise<void> {
  await http.put(`/users/${encodeURIComponent(email)}/role`, { role })
}

export async function removeUser(email: string): Promise<void> {
  await http.delete(`/users/${encodeURIComponent(email)}`)
}
