import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe, type AuthUser } from './api'

interface AuthCtx {
  user: AuthUser | null
  loading: boolean
  refetch: () => Promise<void>
}

const Ctx = createContext<AuthCtx>({ user: null, loading: true, refetch: async () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]     = useState<AuthUser | null>(null)
  const [loading, setLoad]  = useState(true)

  const refetch = async () => {
    const me = await fetchMe()
    setUser(me)
    setLoad(false)
  }

  useEffect(() => { refetch() }, [])

  return <Ctx.Provider value={{ user, loading, refetch }}>{children}</Ctx.Provider>
}

export function useAuth() {
  return useContext(Ctx)
}
