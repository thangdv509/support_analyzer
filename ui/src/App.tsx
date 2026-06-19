import { useState } from 'react'
import { Alert, Avatar, ConfigProvider, Dropdown, Form, Input, Layout, message, Modal, Spin, Tabs, Typography, theme } from 'antd'
import { EditOutlined, LogoutOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import FilterBar from './components/FilterBar'
import QATable from './components/QATable'
import AgentStatsTab from './components/AgentStatsTab'
import ReviewPerformance from './pages/ReviewPerformance'
import ReviewStats from './pages/ReviewStats'
import Analytics from './pages/Analytics'
import UserAnalysis from './pages/UserAnalysis'
import UserManagement from './pages/UserManagement'
import LoginPage from './pages/LoginPage'
import { AuthProvider, useAuth } from './context/AuthContext'
import { logout, updateNickname } from './authApi'
import { fetchStats } from './api'
import type { Filters, Stats } from './types'

const { Content } = Layout
const { Text } = Typography

const DEFAULT_FILTERS: Filters = {
  app: '',
  agent: '',
  date_from: '',
  date_to: '',
  score_min: 0,
  score_max: 10,
  is_resolved: 'all',
  chat_link: '',
}

// ── DB health banner ──────────────────────────────────────────────────────────

interface HealthData { status: string; mongo_error: string | null }

function DBAlert() {
  const { data } = useQuery<HealthData>({
    queryKey: ['health'],
    queryFn: async () => (await axios.get('/api/health')).data,
    refetchInterval: 20_000, retry: false,
  })
  if (!data || data.status === 'ok') return null
  return (
    <Alert
      type="error" showIcon banner
      message="Database connection error"
      description={data.status === 'tunnel_down' ? 'SSH tunnel down.' : `MongoDB: ${data.mongo_error || ''}`}
      style={{ borderRadius: 0, fontSize: 12 }}
    />
  )
}

// ── Stats strip ───────────────────────────────────────────────────────────────

function sc(v: number | null) {
  if (v == null) return '#4b5563'
  if (v >= 9)   return '#22c55e'
  if (v >= 7.5) return '#3b82f6'
  if (v >= 5)   return '#f59e0b'
  return '#ef4444'
}

function StatsStrip({ filters }: { filters: Filters }) {
  const { data } = useQuery<Stats>({
    queryKey: ['stats', filters.app, filters.date_from, filters.date_to],
    queryFn: () => fetchStats({ app: filters.app || undefined, date_from: filters.date_from || undefined, date_to: filters.date_to || undefined }),
    staleTime: 5 * 60_000,
  })
  if (!data) return <div style={{ flex: 1 }} />

  const sep = <div style={{ width: 1, height: 24, background: '#ffffff14', flexShrink: 0 }} />

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
        <span style={{ fontSize: 10, color: '#475569', letterSpacing: 1 }}>TOTAL</span>
        <span style={{ color: '#cbd5e1', fontWeight: 700, fontSize: 16 }}>{data.total.toLocaleString()}</span>
      </div>
      {sep}
      {([['AVG', data.avg_score], ['MIN', data.min_score], ['MAX', data.max_score]] as [string, number | null][]).map(([lbl, val]) => (
        <div key={lbl} style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
          <span style={{ fontSize: 10, color: '#475569', fontWeight: 600, letterSpacing: 0.5 }}>{lbl}</span>
          <span style={{ fontSize: 16, fontWeight: 800, color: sc(val), letterSpacing: -0.5 }}>
            {val != null ? val.toFixed(2) : '—'}
          </span>
        </div>
      ))}
      {Object.keys(data.by_app).length > 0 && sep}
      {Object.entries(data.by_app).map(([app, count]) => (
        <div key={app} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
            background: app === 'DECO' ? '#4f46e5' : '#0e7490', color: '#fff',
          }}>{app}</span>
          <span style={{ color: '#64748b', fontSize: 13, fontWeight: 600 }}>{(count as number).toLocaleString()}</span>
        </div>
      ))}
    </div>
  )
}

// ── User menu (top-right) ─────────────────────────────────────────────────────

const ROLE_COLOR: Record<string, string> = { admin: '#6366f1', manager: '#0891b2', support: '#16a34a' }

function UserMenu() {
  const { user, refetch } = useAuth()
  const queryClient = useQueryClient()
  const [nicknameOpen, setNicknameOpen] = useState(false)
  const [form] = Form.useForm()
  if (!user) return null

  const nickMut = useMutation({
    mutationFn: (nick: string) => updateNickname(nick),
    onSuccess: async () => {
      message.success('Biệt danh đã cập nhật')
      setNicknameOpen(false)
      await refetch()                                    // cập nhật header user menu
      queryClient.invalidateQueries({ queryKey: ['all-users'] })  // ReviewPerformance + ReviewStats
      queryClient.invalidateQueries({ queryKey: ['users'] })       // UserManagement
    },
    onError: () => message.error('Cập nhật thất bại'),
  })

  const items = [
    {
      key: 'info',
      label: (
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontWeight: 600 }}>{user.nickname || user.name}</div>
          {user.nickname && <div style={{ fontSize: 11, color: '#94a3b8' }}>{user.name}</div>}
          <div style={{ fontSize: 11, color: '#94a3b8' }}>{user.email}</div>
          <div style={{ marginTop: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 8px', borderRadius: 99, background: `${ROLE_COLOR[user.role]}22`, color: ROLE_COLOR[user.role] }}>
              {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
            </span>
          </div>
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' as const },
    {
      key: 'nickname',
      icon: <EditOutlined />,
      label: 'Đổi biệt danh',
      onClick: () => { form.setFieldsValue({ nickname: user.nickname || '' }); setNicknameOpen(true) },
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Đăng xuất',
      onClick: async () => { await logout(); await refetch() },
    },
  ]

  return (
    <>
      <Dropdown menu={{ items }} placement="bottomRight" trigger={['click']}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '4px 8px', borderRadius: 8 }}>
          {user.picture
            ? <img src={user.picture} alt="" style={{ width: 28, height: 28, borderRadius: '50%' }} />
            : <Avatar size={28} icon={<UserOutlined />} />}
          <Text style={{ color: '#94a3b8', fontSize: 12 }}>{user.nickname || user.name.split(' ')[0]}</Text>
        </div>
      </Dropdown>

      <Modal title="Đổi biệt danh" open={nicknameOpen}
        onCancel={() => setNicknameOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={nickMut.isPending} okText="Lưu">
        <Form form={form} layout="vertical"
          onFinish={v => nickMut.mutate(v.nickname)}>
          <Form.Item name="nickname" label="Biệt danh hiển thị"
            extra="Để trống để dùng tên Google mặc định">
            <Input placeholder={user.name} maxLength={40} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard() {
  const { user } = useAuth()
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)

  const canManageUsers = user?.role === 'admin' || user?.role === 'manager'

  return (
    <Layout style={{ minHeight: '100vh', background: '#f1f5f9' }}>
      {/* Topbar */}
      <div style={{
        background: '#0f172a',
        borderBottom: '1px solid #1e293b',
        padding: '0 20px',
        height: 48,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
      }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 8,
            background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, boxShadow: '0 0 10px #6366f155',
          }}>▦</div>
          <span style={{ color: '#f1f5f9', fontWeight: 700, fontSize: 14, letterSpacing: -0.3 }}>QA Dashboard</span>
          <span style={{ fontSize: 10, color: '#475569', background: '#1e293b', border: '1px solid #334155', borderRadius: 4, padding: '1px 6px' }}>
            SUPPORT ANALYZER
          </span>
        </div>

        {/* Stats */}
        <StatsStrip filters={filters} />

        {/* User menu */}
        <div style={{ flexShrink: 0 }}>
          <UserMenu />
        </div>
      </div>

      <DBAlert />

      <Content style={{ padding: '12px 16px 0' }}>
        <Tabs
          size="small"
          tabBarStyle={{ marginBottom: 8 }}
          items={[
            {
              key: 'records',
              label: <span style={{ fontWeight: 600 }}>📋 Records</span>,
              children: (
                <>
                  <FilterBar filters={filters} onChange={setFilters} />
                  <QATable filters={filters} />
                </>
              ),
            },
            {
              key: 'agents',
              label: <span style={{ fontWeight: 600 }}>📊 Agent Stats</span>,
              children: <AgentStatsTab />,
            },
            {
              key: 'reviews',
              label: <span style={{ fontWeight: 600 }}>⭐ Review Performance</span>,
              children: <ReviewPerformance />,
            },
            ...(canManageUsers ? [{
              key: 'review-stats',
              label: <span style={{ fontWeight: 600 }}>📈 Review Stats</span>,
              children: <ReviewStats />,
            }] : []),
            ...(canManageUsers ? [{
              key: 'analytics',
              label: <span style={{ fontWeight: 600 }}>📊 Analytics</span>,
              children: <Analytics />,
            }] : []),
            ...(canManageUsers ? [{
              key: 'analysis',
              label: <span style={{ fontWeight: 600 }}>👤 User Analysis</span>,
              children: <UserAnalysis />,
            }] : []),
            ...(canManageUsers ? [{
              key: 'users',
              label: (
                <span style={{ fontWeight: 600 }}>
                  <TeamOutlined style={{ marginRight: 4 }} />Users
                </span>
              ),
              children: <UserManagement />,
            }] : []),
          ]}
        />
      </Content>
    </Layout>
  )
}

// ── Root — auth gate ──────────────────────────────────────────────────────────

function AuthGate() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!user) return <LoginPage />
  return <Dashboard />
}

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#6366f1',
          borderRadius: 8,
          fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
          colorBgContainer: '#ffffff',
          colorBorder: '#e2e8f0',
        },
        components: {
          Card:      { borderRadius: 10, boxShadow: '0 1px 3px #0000000d' },
          Tabs:      { inkBarColor: '#6366f1', itemSelectedColor: '#6366f1' },
          Segmented: { borderRadius: 8 },
          Button:    { borderRadius: 8 },
          Select:    { borderRadius: 8 },
          DatePicker:{ borderRadius: 8 },
          Table:     { borderRadius: 8 },
        },
      }}
    >
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </ConfigProvider>
  )
}
