import { useEffect } from 'react'
import { useSearchParams } from '../hooks/useSearchParams'
import { loginUrl } from '../authApi'

const ROLE_LABELS: Record<string, string> = {
  not_authorized: 'Email này chưa được cấp quyền truy cập. Liên hệ admin để được thêm vào hệ thống.',
  oauth_failed:   'Đăng nhập thất bại. Vui lòng thử lại.',
}

export default function LoginPage() {
  const params = useSearchParams()
  const error  = params.get('error')
  const email  = params.get('email')

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: "'Inter', 'Segoe UI', sans-serif",
    }}>
      <div style={{
        background: '#ffffff0d',
        backdropFilter: 'blur(20px)',
        border: '1px solid #ffffff18',
        borderRadius: 20,
        padding: '48px 44px',
        width: 380,
        textAlign: 'center',
        boxShadow: '0 25px 60px #00000055',
      }}>
        {/* Logo */}
        <div style={{
          width: 56, height: 56, borderRadius: 14,
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 26, marginBottom: 20,
          boxShadow: '0 0 24px #6366f155',
        }}>
          ▦
        </div>

        <h1 style={{ color: '#f1f5f9', fontSize: 22, fontWeight: 700, margin: '0 0 4px', letterSpacing: -0.5 }}>
          QA Dashboard
        </h1>
        <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 32px' }}>
          Support Analyzer — Secomus
        </p>

        {/* Error banner */}
        {error && (
          <div style={{
            background: '#ff444422',
            border: '1px solid #ff444444',
            borderRadius: 8,
            padding: '10px 14px',
            marginBottom: 20,
            fontSize: 13,
            color: '#fca5a5',
            textAlign: 'left',
          }}>
            {ROLE_LABELS[error] || 'Đăng nhập thất bại.'}
            {email && error === 'not_authorized' && (
              <div style={{ marginTop: 4, color: '#94a3b8', fontSize: 12 }}>
                Email: <strong>{email}</strong>
              </div>
            )}
          </div>
        )}

        {/* Sign in button */}
        <a
          href={loginUrl()}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            background: '#fff',
            color: '#1e293b',
            borderRadius: 10,
            padding: '13px 20px',
            fontWeight: 600,
            fontSize: 15,
            textDecoration: 'none',
            transition: 'all 0.15s',
            boxShadow: '0 2px 8px #00000033',
          }}
          onMouseEnter={e => (e.currentTarget.style.transform = 'translateY(-1px)')}
          onMouseLeave={e => (e.currentTarget.style.transform = 'none')}
        >
          <GoogleIcon />
          Đăng nhập với Google
        </a>

        <p style={{ color: '#334155', fontSize: 11, marginTop: 24 }}>
          Chỉ email được admin cấp quyền mới có thể đăng nhập.
        </p>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 48 48">
      <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.6 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.2 6.7 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20c11 0 20-9 20-20 0-1.3-.1-2.7-.4-3.9z"/>
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.6 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.2 6.7 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
      <path fill="#4CAF50" d="M24 44c5.2 0 10-2 13.6-5.1l-6.3-5.3C29.4 35.5 26.8 36 24 36c-5.2 0-9.6-3.3-11.3-8H6.1C9.4 36.1 16.2 44 24 44z"/>
      <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.3 4.2-4.2 5.6l6.3 5.3C41.7 35.3 44 30 44 24c0-1.3-.1-2.7-.4-3.9z"/>
    </svg>
  )
}
