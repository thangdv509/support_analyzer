import { useState } from 'react'
import { Alert, ConfigProvider, Layout, Tabs, theme } from 'antd'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import FilterBar from './components/FilterBar'
import QATable from './components/QATable'
import AgentStatsTab from './components/AgentStatsTab'
import { fetchStats } from './api'
import type { Filters, Stats } from './types'

const { Content } = Layout

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

// ── Helpers ───────────────────────────────────────────────────────────────────

function sc(v: number | null) {
  if (v == null) return '#4b5563'
  if (v >= 9) return '#22c55e'
  if (v >= 7.5) return '#3b82f6'
  if (v >= 5) return '#f59e0b'
  return '#ef4444'
}

// ── DB banner ─────────────────────────────────────────────────────────────────

interface HealthData { status: string; mongo_error: string | null; tcp_open: boolean }

function DBAlert() {
  const { data } = useQuery<HealthData>({
    queryKey: ['health'],
    queryFn: async () => (await axios.get('/api/health')).data,
    refetchInterval: 20_000,
    retry: false,
  })
  if (!data || data.status === 'ok') return null
  return (
    <Alert
      type="error"
      showIcon
      banner
      message="Database connection error"
      description={data.status === 'tunnel_down' ? 'SSH tunnel down.' : `MongoDB: ${data.mongo_error || ''}`}
      style={{ borderRadius: 0, fontSize: 12 }}
    />
  )
}

// ── Topbar ────────────────────────────────────────────────────────────────────

function Topbar({ filters }: { filters: Filters }) {
  const { data } = useQuery<Stats>({
    queryKey: ['stats', filters.app, filters.date_from, filters.date_to],
    queryFn: () => fetchStats({
      app: filters.app || undefined,
      date_from: filters.date_from || undefined,
      date_to: filters.date_to || undefined,
    }),
    staleTime: 30_000,
  })

  const sep = <div style={{ width: 1, height: 24, background: '#ffffff12', flexShrink: 0 }} />

  return (
    <div style={{
      background: '#0f172a',
      borderBottom: '1px solid #1e293b',
      padding: '0 20px',
      height: 52,
      display: 'flex',
      alignItems: 'center',
      gap: 0,
    }}>
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 20 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 8,
          background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, boxShadow: '0 0 10px #6366f155',
        }}>
          ▦
        </div>
        <span style={{ color: '#f1f5f9', fontWeight: 700, fontSize: 14, letterSpacing: -0.3 }}>
          QA Dashboard
        </span>
        <span style={{
          fontSize: 10, color: '#475569',
          background: '#1e293b', border: '1px solid #334155',
          borderRadius: 4, padding: '1px 6px', letterSpacing: 0.3,
        }}>
          SUPPORT ANALYZER
        </span>
      </div>

      {/* Divider */}
      <div style={{ flex: 1 }} />

      {/* Stats */}
      {data && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>

          {/* Total */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
            <span style={{ fontSize: 11, color: '#475569', fontWeight: 500 }}>TOTAL</span>
            <span style={{ color: '#cbd5e1', fontWeight: 700, fontSize: 16, letterSpacing: -0.5 }}>
              {data.total.toLocaleString()}
            </span>
          </div>

          {sep}

          {/* Avg / Min / Max */}
          {([
            ['AVG', data.avg_score],
            ['MIN', data.min_score],
            ['MAX', data.max_score],
          ] as [string, number | null][]).map(([lbl, val]) => (
            <div key={lbl} style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <span style={{ fontSize: 10, color: '#475569', fontWeight: 600, letterSpacing: 0.5 }}>
                {lbl}
              </span>
              <span style={{
                fontSize: 16, fontWeight: 800, letterSpacing: -0.5,
                color: sc(val),
                textShadow: val != null && val >= 9 ? '0 0 8px #22c55e66' : 'none',
              }}>
                {val != null ? val.toFixed(2) : '—'}
              </span>
            </div>
          ))}

          {Object.keys(data.by_app).length > 0 && sep}

          {/* By app pills */}
          {Object.entries(data.by_app).map(([app, count]) => (
            <div key={app} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                background: app === 'DECO' ? '#4f46e5' : '#0e7490',
                color: '#fff',
                letterSpacing: 0.2,
              }}>
                {app}
              </span>
              <span style={{ color: '#64748b', fontSize: 13, fontWeight: 600 }}>
                {count.toLocaleString()}
              </span>
            </div>
          ))}

          {/* Active date range */}
          {(filters.date_from || filters.date_to) && (
            <>
              {sep}
              <span style={{ fontSize: 11, color: '#475569' }}>
                {filters.date_from || '…'} → {filters.date_to || 'now'}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)

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
          Card: { borderRadius: 10, boxShadow: '0 1px 3px #0000000d' },
          Tabs: { inkBarColor: '#6366f1', itemSelectedColor: '#6366f1' },
          Segmented: { borderRadius: 8 },
          Button: { borderRadius: 8 },
          Select: { borderRadius: 8 },
          DatePicker: { borderRadius: 8 },
          Table: { borderRadius: 8 },
        },
      }}
    >
      <Layout style={{ minHeight: '100vh', background: '#f1f5f9' }}>
        <Topbar filters={filters} />
        <DBAlert />
        <Content style={{ padding: '12px 16px 0' }}>
          <Tabs
            size="small"
            tabBarStyle={{ marginBottom: 8 }}
            items={[
              {
                key: 'records',
                label: <span style={{ fontWeight: 600, letterSpacing: -0.2 }}>📋 Records</span>,
                children: (
                  <>
                    <FilterBar filters={filters} onChange={setFilters} />
                    <QATable filters={filters} />
                  </>
                ),
              },
              {
                key: 'agents',
                label: <span style={{ fontWeight: 600, letterSpacing: -0.2 }}>📊 Agent Stats</span>,
                children: <AgentStatsTab />,
              },
            ]}
          />
        </Content>
      </Layout>
    </ConfigProvider>
  )
}
