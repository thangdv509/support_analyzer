import { useState } from 'react'
import {
  Button,
  DatePicker,
  Divider,
  Progress,
  Segmented,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import { FilterOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchAgents, fetchStats } from '../api'
import type { Stats } from '../types'

const { RangePicker } = DatePicker
const { Text } = Typography

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentRow { agent: string; count: number; avg_score: number | null }

interface Params { app: string; date_from: string; date_to: string; agent: string }

const DEFAULT_PARAMS: Params = { app: '', date_from: '', date_to: '', agent: '' }

// ── Helpers ───────────────────────────────────────────────────────────────────

const PRESETS: { label: string; range: () => [Dayjs, Dayjs] }[] = [
  { label: 'Hôm nay',    range: () => [dayjs(), dayjs()] },
  { label: '7 ngày',     range: () => [dayjs().subtract(6, 'day'), dayjs()] },
  { label: '30 ngày',    range: () => [dayjs().subtract(29, 'day'), dayjs()] },
  { label: 'Tháng này',  range: () => [dayjs().startOf('month'), dayjs()] },
  { label: 'Tháng trước',range: () => [dayjs().subtract(1,'month').startOf('month'), dayjs().subtract(1,'month').endOf('month')] },
]

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

  // Build rows — optionally filter by selected agent
  const agentRows: AgentRow[] = Object.entries(data?.by_agent || {})
    .map(([agent, v]) => ({ agent, count: v.count, avg_score: v.avg_score }))
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
      render: (name: string) => (
        <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{name}</span>
      ),
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
        maxWidth: 560,  // compact width — không cần full width
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
    </div>
  )
}
