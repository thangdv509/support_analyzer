import axios from 'axios'

export type Role = 'admin' | 'manager' | 'support'

export interface AuthUser {
  email: string
  name: string
  nickname: string
  picture: string
  role: Role
}

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

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const { data } = await http.get('/auth/me')
    return data
  } catch {
    return null
  }
}

export function loginUrl() {
  return '/api/auth/login'
}

export async function logout(): Promise<void> {
  await http.post('/auth/logout')
}

export async function updateNickname(nickname: string): Promise<void> {
  await http.put('/auth/me', { nickname })
}

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
