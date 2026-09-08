import axios from 'axios'

export type Role = 'admin' | 'manager' | 'support'

export interface AuthUser {
  email: string
  name: string
  nickname: string
  picture: string
  role: Role
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
