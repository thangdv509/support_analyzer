import { useState } from 'react'
import {
  Avatar,
  Button,
  DatePicker,
  Divider,
  Modal,
  Progress,
  Segmented,
  Select,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { BarChartOutlined, BulbOutlined, FilterOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import dayjs, { type Dayjs } from 'dayjs'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { fetchAgents, fetchStats } from './api'
import type { Stats } from './types'

const http = axios.create({ baseURL: '/api', withCredentials: true })

const { RangePicker } = DatePicker
const { Text } = Typography

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentRow { agent: string; count: number; avg_score: number | null }
interface UserInfo { email: string; name: string; nickname: string; picture: string; role: string }

interface Params { app: string; date_from: string; date_to: string; agent: string }

const DEFAULT_PARAMS: Params = { app: '', date_from: '', date_to: '', agent: '' }

// ── Helpers ───────────────────────────────────────────────────────────────────

const PRESETS: { label: string; range: () => [Dayjs, Dayjs] }[] = [
  { label: 'Hôm qua',    range: () => [dayjs().subtract(1, 'day'), dayjs().subtract(1, 'day')] },
  { label: 'Hôm nay',    range: () => [dayjs(), dayjs()] },
  { label: '7 ngày',     range: () => [dayjs().subtract(6, 'day'), dayjs()] },
  { label: '30 ngày',    range: () => [dayjs().subtract(29, 'day'), dayjs()] },
  { label: 'Tháng này',  range: () => [dayjs().startOf('month'), dayjs()] },
  { label: 'Tháng trước',range: () => [dayjs().subtract(1,'month').startOf('month'), dayjs().subtract(1,'month').endOf('month')] },
]

const APP_COLOR: Record<string, string> = { SearchPie: '#7c3aed', DECO: '#0e7490' }

// ── Trend Modal ───────────────────────────────────────────────────────────────

interface TrendPoint { date: string; [app: string]: number | string }

function AgentTrendModal({ agent, name, onClose }: { agent: string; name: string; onClose: () => void }) {
  const [groupBy, setGroupBy] = useState<'day'|'month'|'year'>('month')
  const [range, setRange] = useState<[Dayjs,Dayjs]|null>([dayjs().subtract(5,'month').startOf('month'), dayjs()])

  const dateFrom = range?.[0]?.format('YYYY-MM-DD') || ''
  const dateTo   = range?.[1]?.format('YYYY-MM-DD') || ''

  const { data, isLoading } = useQuery({
    queryKey: ['review-trend', agent, groupBy, dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams({ agent, group_by: groupBy })
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo)   params.set('date_to', dateTo)
      return (await http.get(`/review-trend?${params}`)).data as { data: TrendPoint[]; apps: string[] }
    },
    staleTime: 60_000,
    enabled: !!agent,
  })

  const apps = data?.apps || []
  const chartData = data?.data || []

  return (
    <Modal
      title={<span>Trend reviews — <strong>{name}</strong></span>}
      open onCancel={onClose} footer={null} width={700}
    >
      {/* Controls */}
      <div style={{ display:'flex', gap:16, alignItems:'flex-end', marginBottom:16, flexWrap:'wrap' }}>
        <div>
          <Typography.Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>KHOẢNG NGÀY</Typography.Text>
          <DatePicker.RangePicker size="small" format="DD/MM/YYYY" value={range}
            onChange={v => setRange(v as [Dayjs,Dayjs]|null)} style={{ width:220 }} allowClear />
        </div>
        <div>
          <Typography.Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>NHÓM THEO</Typography.Text>
          <Segmented size="small" value={groupBy} onChange={v => setGroupBy(v as 'day'|'month'|'year')}
            options={[
              { label:'Ngày',   value:'day'   },
              { label:'Tháng',  value:'month' },
              { label:'Năm',    value:'year'  },
            ]}
          />
        </div>
      </div>

      {/* Chart */}
      {isLoading ? (
        <div style={{ height:280, display:'flex', alignItems:'center', justifyContent:'center', color:'#94a3b8' }}>Đang tải…</div>
      ) : chartData.length === 0 ? (
        <div style={{ height:280, display:'flex', alignItems:'center', justifyContent:'center', color:'#94a3b8' }}>Không có dữ liệu</div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top:4, right:12, left:-10, bottom:4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="date" tick={{ fontSize:11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize:11 }} />
            <RTooltip contentStyle={{ fontSize:12 }} />
            <Legend iconType="circle" wrapperStyle={{ fontSize:12 }} />
            {apps.map(a => (
              <Line key={a} type="monotone" dataKey={a}
                stroke={APP_COLOR[a] || '#6366f1'}
                strokeWidth={2} dot={{ r:3 }} activeDot={{ r:5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </Modal>
  )
}

// ── Summary Modal ─────────────────────────────────────────────────────────────

interface AgentSummary {
  chat_count: number
  sampled_count: number
  strengths: string[]
  weaknesses: string[]
  improvements: string[]
  common_issues: string[]
}

const SUMMARY_SECTIONS: { key: keyof Pick<AgentSummary, 'strengths'|'weaknesses'|'improvements'|'common_issues'>; label: string; color: string }[] = [
  { key: 'common_issues', label: 'Vấn đề thường gặp', color: '#6366f1' },
  { key: 'strengths',     label: 'Ưu điểm',           color: '#16a34a' },
  { key: 'weaknesses',    label: 'Nhược điểm',         color: '#ef4444' },
  { key: 'improvements',  label: 'Cần cải thiện',      color: '#f59e0b' },
]

function AgentSummaryModal({ agent, name, app, dateFrom, dateTo, onClose }: {
  agent: string; name: string; app: string; dateFrom: string; dateTo: string; onClose: () => void
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['agent-summary', agent, app, dateFrom, dateTo],
    queryFn: async () => {
      const params = new URLSearchParams({ agent })
      if (app)      params.set('app', app)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo)   params.set('date_to', dateTo)
      return (await http.get(`/agent-summary?${params}`)).data as AgentSummary
    },
    staleTime: 5 * 60_000,
    retry: false,
    enabled: !!agent,
  })

  return (
    <Modal
      title={<span>Tổng hợp đánh giá — <strong>{name}</strong></span>}
      open onCancel={onClose} footer={null} width={640}
    >
      {isLoading && (
        <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin tip="Đang tổng hợp bằng AI…" />
        </div>
      )}
      {isError && (
        <div style={{ padding: 20, textAlign: 'center', color: '#ef4444', fontSize: 13 }}>
          {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
            || 'Không thể tổng hợp — thử lại sau.'}
        </div>
      )}
      {data && (
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Dựa trên {data.chat_count.toLocaleString()} chat đã chấm
            {data.sampled_count < data.chat_count ? ` (lấy mẫu ${data.sampled_count} chat gần nhất)` : ''} trong khoảng ngày đã chọn.
          </Text>
          {SUMMARY_SECTIONS.map(s => (
            <div key={s.key} style={{ marginTop: 18 }}>
              <Text strong style={{ color: s.color, fontSize: 13 }}>{s.label}</Text>
              {data[s.key].length === 0 ? (
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>Không có dữ liệu</div>
              ) : (
                <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
                  {data[s.key].map((line, i) => (
                    <li key={i} style={{ fontSize: 13, marginBottom: 4, lineHeight: 1.5 }}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sc(v: number | null) {
  if (v == null) return '#bbb'
  if (v >= 9)   return '#22c55e'
  if (v >= 7.5) return '#3b82f6'
  if (v >= 5)   return '#f59e0b'
  return '#ef4444'
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score == null) return <span style={{ color: '#bbb' }}>—</span>
  const color = sc(score)
  return (
    <span style={{
      fontWeight: 700, fontSize: 14, color,
      background: `${color}18`, borderRadius: 4, padding: '1px 8px',
    }}>
      {score.toFixed(2)}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AgentStatsTab() {
  const [local, setLocal] = useState<Params>(DEFAULT_PARAMS)
  const [applied, setApplied] = useState<Params>(DEFAULT_PARAMS)
  const [dateValue, setDateValue] = useState<[Dayjs, Dayjs] | null>(null)
  const [trendAgent, setTrendAgent] = useState<{ email: string; name: string } | null>(null)
  const [summaryAgent, setSummaryAgent] = useState<{ email: string; name: string } | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents', local.app],
    queryFn: () => fetchAgents(local.app),
    staleTime: 60_000,
  })

  const { data, isLoading } = useQuery<Stats>({
    queryKey: ['agent-stats', applied.app, applied.date_from, applied.date_to],
    queryFn: () => fetchStats({
      app: applied.app || undefined,
      date_from: applied.date_from || undefined,
      date_to: applied.date_to || undefined,
    }),
    staleTime: 30_000,
  })

  const { data: agentMap = {} } = useQuery<Record<string, UserInfo>>({
    queryKey: ['agent-map'],
    queryFn: () => http.get('/users/agent-map').then(r => r.data),
    staleTime: 5 * 60_000,
  })

  const setDate = (range: [Dayjs, Dayjs] | null) => {
    setDateValue(range)
    setLocal(p => ({
      ...p,
      date_from: range?.[0]?.format('YYYY-MM-DD') || '',
      date_to:   range?.[1]?.format('YYYY-MM-DD') || '',
    }))
  }

  const apply = () => setApplied(local)

  const reset = () => {
    setLocal(DEFAULT_PARAMS)
    setApplied(DEFAULT_PARAMS)
    setDateValue(null)
  }

  // Only show agents linked to a user account
  const agentRows: AgentRow[] = Object.entries(data?.by_agent || {})
    .map(([agent, v]) => ({ agent, count: v.count, avg_score: v.avg_score }))
    .filter(r => agentMap[r.agent] !== undefined)
    .filter(r => !applied.agent || r.agent === applied.agent)
    .sort((a, b) => (b.avg_score ?? 0) - (a.avg_score ?? 0))

  const activeCount = [applied.app, applied.agent, applied.date_from].filter(Boolean).length

  // ── Columns ─────────────────────────────────────────────────────────────────

  const columns = [
    {
      title: '#', key: 'rank', width: 36,
      render: (_: unknown, __: AgentRow, idx: number) => (
        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 500 }}>{idx + 1}</span>
      ),
    },
    {
      title: 'Agent', dataIndex: 'agent', key: 'agent',
      render: (name: string) => {
        const u = agentMap[name]
        if (!u) return <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{name}</span>
        const displayName = u.nickname?.trim() || u.name
        return (
          <Tooltip title={<div>
            {u.nickname?.trim() && u.nickname !== u.name && <div style={{ fontSize: 11, color: '#94a3b8' }}>{u.name}</div>}
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{u.email}</div>
          </div>} placement="right">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {u.picture
                ? <img src={u.picture} alt="" style={{ width: 28, height: 28, borderRadius: '50%', flexShrink: 0 }} />
                : <Avatar size={28} icon={<UserOutlined />} style={{ flexShrink: 0 }} />
              }
              <div>
                <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.3 }}>{displayName}</div>
                {u.nickname?.trim() && u.nickname !== u.name && (
                  <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.2 }}>{u.name}</div>
                )}
              </div>
            </div>
          </Tooltip>
        )
      },
    },
    {
      title: 'Chats', dataIndex: 'count', key: 'count', width: 64,
      align: 'right' as const,
      sorter: (a: AgentRow, b: AgentRow) => a.count - b.count,
      render: (v: number) => (
        <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500 }}>{v.toLocaleString()}</span>
      ),
    },
    {
      title: 'Avg /10', dataIndex: 'avg_score', key: 'avg_score',
      width: 180,
      defaultSortOrder: 'descend' as const,
      sorter: (a: AgentRow, b: AgentRow) => (a.avg_score ?? 0) - (b.avg_score ?? 0),
      render: (score: number | null) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontSize: 13, fontWeight: 700, color: sc(score),
            minWidth: 36, textAlign: 'right',
          }}>
            {score != null ? score.toFixed(2) : '—'}
          </span>
          <Progress
            percent={score != null ? Math.round((score / 10) * 100) : 0}
            showInfo={false}
            strokeColor={sc(score)}
            trailColor="#e2e8f0"
            style={{ flex: 1, marginBottom: 0 }}
            size={[undefined, 6] as unknown as 'small'}
          />
        </div>
      ),
    },
    {
      title: '', key: 'actions', width: 76,
      render: (_: unknown, row: AgentRow) => {
        const u = agentMap[row.agent]
        const name = u ? (u.nickname?.trim() || u.name) : row.agent
        return (
          <span style={{ display: 'flex', gap: 2 }}>
            <Tooltip title="Xem trend reviews">
              <Button size="small" type="text" icon={<BarChartOutlined />}
                style={{ color: '#6366f1' }}
                onClick={() => setTrendAgent({ email: row.agent, name })} />
            </Tooltip>
            <Tooltip title="Tổng hợp đánh giá bằng AI">
              <Button size="small" type="text" icon={<BulbOutlined />}
                style={{ color: '#f59e0b' }}
                onClick={() => setSummaryAgent({ email: row.agent, name })} />
            </Tooltip>
          </span>
        )
      },
    },
  ]

  return (
    <div>
      {/* ── Filter bar ────────────────────────────────────────────── */}
      <div style={{
        background: '#fff', borderRadius: 10,
        boxShadow: '0 1px 4px #0001',
        padding: '10px 16px', marginBottom: 10,
        display: 'flex', flexWrap: 'wrap', gap: '8px 20px', alignItems: 'flex-end',
      }}>

        {/* Date */}
        <div>
          <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>KHOẢNG NGÀY</Text>
          <RangePicker
            size="small" format="DD/MM/YYYY"
            value={dateValue}
            onChange={v => setDate(v as [Dayjs, Dayjs] | null)}
            style={{ width: 210 }} allowClear
            placeholder={['Từ ngày', 'Đến ngày']}
          />
          <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {PRESETS.map(p => (
              <Tag key={p.label}
                style={{ cursor: 'pointer', fontSize: 11, padding: '0 6px', margin: 0 }}
                color={dateValue?.[0]?.format('YYYY-MM-DD') === p.range()[0].format('YYYY-MM-DD') ? 'blue' : undefined}
                onClick={() => setDate(p.range())}
              >
                {p.label}
              </Tag>
            ))}
          </div>
        </div>

        <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

        {/* App */}
        <div>
          <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>APP</Text>
          <Segmented size="small"
            value={local.app || '__all__'}
            onChange={v => setLocal(p => ({ ...p, app: v === '__all__' ? '' : String(v) }))}
            options={[
              { label: 'All', value: '__all__' },
              { label: <span style={{ color: '#722ed1', fontWeight: 600 }}>DECO</span>, value: 'DECO' },
              { label: <span style={{ color: '#13c2c2', fontWeight: 600 }}>SearchPie</span>, value: 'SearchPie' },
            ]}
          />
        </div>

        <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

        {/* Agent */}
        <div>
          <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>AGENT</Text>
          <Select size="small" style={{ width: 170 }}
            placeholder="Tất cả" allowClear showSearch
            value={local.agent || undefined}
            onChange={v => setLocal(p => ({ ...p, agent: v || '' }))}
            filterOption={(input, opt) =>
              (opt?.label as string)?.toLowerCase().includes(input.toLowerCase())
            }
            options={agents.map(a => ({ label: a, value: a }))}
          />
        </div>

        {/* Buttons */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <Button size="small" icon={<ReloadOutlined />} onClick={reset} style={{ color: '#888' }}>
            Reset
          </Button>
          <Button type="primary" size="small" icon={<FilterOutlined />} onClick={apply} style={{ minWidth: 90 }}>
            Filter{activeCount > 0 ? ` (${activeCount})` : ''}
          </Button>
        </div>
      </div>

      {/* ── Overview strip ───────────────────────────────────────── */}
      {data && (
        <div style={{
          display: 'flex', gap: 20, alignItems: 'center',
          background: '#fff', borderRadius: 10,
          boxShadow: '0 1px 4px #0001',
          padding: '8px 20px', marginBottom: 10,
          flexWrap: 'wrap',
        }}>
          {([
            ['Total', data.total, null],
            ['Avg', data.avg_score, '/10'],
            ['Min', data.min_score, '/10'],
            ['Max', data.max_score, '/10'],
          ] as [string, number | null, string | null][]).map(([lbl, val, suffix]) => (
            <div key={lbl} style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.5 }}>{lbl}</Text>
              <span style={{ fontWeight: 800, fontSize: 16, color: lbl === 'Total' ? '#0f172a' : sc(val as number | null), letterSpacing: -0.5 }}>
                {val != null ? (lbl === 'Total' ? (val as number).toLocaleString() : (val as number).toFixed(2)) : '—'}
              </span>
              {suffix && val != null && <Text type="secondary" style={{ fontSize: 11 }}>{suffix}</Text>}
            </div>
          ))}

          {Object.entries(data.by_app).map(([app, count]) => (
            <div key={app} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 99,
                background: app === 'DECO' ? '#4f46e5' : '#0e7490', color: '#fff',
              }}>{app}</span>
              <Text style={{ fontWeight: 600 }}>{(count as number).toLocaleString()}</Text>
            </div>
          ))}

          {(applied.date_from || applied.date_to) && (
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
              {applied.date_from || '…'} → {applied.date_to || 'now'}
            </Text>
          )}
        </div>
      )}

      {/* ── Table ────────────────────────────────────────────────── */}
      <div style={{
        background: '#fff', borderRadius: 10,
        boxShadow: '0 1px 4px #0001', overflow: 'hidden',
        maxWidth: 560,
        margin: '0 auto',
      }}>
        <div style={{ padding: '8px 14px 6px', borderBottom: '1px solid #f1f5f9', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text strong style={{ fontSize: 13 }}>Agent performance</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>{agentRows.length} agents</Text>
        </div>
        <Table<AgentRow>
          dataSource={agentRows}
          columns={columns}
          rowKey="agent"
          loading={isLoading}
          pagination={false}
          size="small"
          style={{ fontSize: 12 }}
          rowClassName={() => 'agent-row'}
        />
      </div>

      {trendAgent && (
        <AgentTrendModal
          agent={trendAgent.email}
          name={trendAgent.name}
          onClose={() => setTrendAgent(null)}
        />
      )}

      {summaryAgent && (
        <AgentSummaryModal
          agent={summaryAgent.email}
          name={summaryAgent.name}
          app={applied.app}
          dateFrom={applied.date_from}
          dateTo={applied.date_to}
          onClose={() => setSummaryAgent(null)}
        />
      )}
    </div>
  )
}
