import { useEffect, useState } from 'react'
import {
  Button,
  DatePicker,
  Divider,
  Input,
  InputNumber,
  Segmented,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { FilterOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchAgents } from '../api'
import type { Filters } from '../types'

const { RangePicker } = DatePicker
const { Text } = Typography

interface Props {
  filters: Filters
  onChange: (f: Filters) => void
}

// ── Quick date presets ────────────────────────────────────────────────────────

const PRESETS: { label: string; range: () => [Dayjs, Dayjs] }[] = [
  { label: 'Hôm nay', range: () => [dayjs(), dayjs()] },
  { label: '7 ngày', range: () => [dayjs().subtract(6, 'day'), dayjs()] },
  { label: '30 ngày', range: () => [dayjs().subtract(29, 'day'), dayjs()] },
  { label: 'Tháng này', range: () => [dayjs().startOf('month'), dayjs()] },
  { label: 'Tháng trước', range: () => [
    dayjs().subtract(1, 'month').startOf('month'),
    dayjs().subtract(1, 'month').endOf('month'),
  ]},
]

// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT: Filters = {
  app: '',
  agent: '',
  date_from: '',
  date_to: '',
  score_min: 0,
  score_max: 10,
  is_resolved: 'all',
  chat_link: '',
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function FilterBar({ filters, onChange }: Props) {
  // local state (applied on click Filter)
  const [local, setLocal] = useState<Filters>(filters)
  const [dateValue, setDateValue] = useState<[Dayjs, Dayjs] | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents', local.app],
    queryFn: () => fetchAgents(local.app),
    staleTime: 60_000,
  })

  // count active filters
  const activeCount = [
    local.app,
    local.agent,
    local.date_from,
    local.score_min > 0 || local.score_max < 10,
    local.is_resolved !== 'all',
  ].filter(Boolean).length

  const apply = () => onChange(local)

  const reset = () => {
    setLocal(DEFAULT)
    setDateValue(null)
    onChange(DEFAULT)
  }

  const setDate = (range: [Dayjs, Dayjs] | null) => {
    setDateValue(range)
    setLocal((prev) => ({
      ...prev,
      date_from: range?.[0]?.format('YYYY-MM-DD') || '',
      date_to: range?.[1]?.format('YYYY-MM-DD') || '',
    }))
  }

  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 10,
        boxShadow: '0 1px 4px #0001',
        padding: '10px 16px',
        marginBottom: 10,
        display: 'flex',
        flexWrap: 'wrap',
        gap: '8px 20px',
        alignItems: 'flex-end',
      }}
    >
      {/* ── Date ────────────────────────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          KHOẢNG NGÀY
        </Text>
        <Space.Compact>
          <RangePicker
            size="small"
            format="DD/MM/YYYY"
            value={dateValue}
            onChange={(v) => setDate(v as [Dayjs, Dayjs] | null)}
            style={{ width: 210 }}
            allowClear
            placeholder={['Từ ngày', 'Đến ngày']}
          />
        </Space.Compact>
        <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {PRESETS.map((p) => (
            <Tag
              key={p.label}
              style={{ cursor: 'pointer', fontSize: 11, padding: '0 6px', margin: 0 }}
              color={
                dateValue?.[0]?.format('YYYY-MM-DD') === p.range()[0].format('YYYY-MM-DD')
                  ? 'blue'
                  : undefined
              }
              onClick={() => setDate(p.range())}
            >
              {p.label}
            </Tag>
          ))}
        </div>
      </div>

      <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

      {/* ── App ─────────────────────────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          APP
        </Text>
        <Segmented
          size="small"
          value={local.app || '__all__'}
          onChange={(v) =>
            setLocal((p) => ({ ...p, app: v === '__all__' ? '' : String(v) }))
          }
          options={[
            { label: 'All', value: '__all__' },
            {
              label: (
                <span style={{ color: '#722ed1', fontWeight: 600 }}>DECO</span>
              ),
              value: 'DECO',
            },
            {
              label: (
                <span style={{ color: '#13c2c2', fontWeight: 600 }}>SearchPie</span>
              ),
              value: 'SearchPie',
            },
          ]}
        />
      </div>

      <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

      {/* ── Status ──────────────────────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          STATUS
        </Text>
        <Segmented
          size="small"
          value={local.is_resolved}
          onChange={(v) => setLocal((p) => ({ ...p, is_resolved: v as Filters['is_resolved'] }))}
          options={[
            { label: 'All', value: 'all' },
            { label: '○ Open', value: 'false' },
            { label: '✓ Resolved', value: 'true' },
          ]}
        />
      </div>

      <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

      {/* ── Agent ───────────────────────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          AGENT
        </Text>
        <Select
          size="small"
          style={{ width: 170 }}
          placeholder="Tất cả"
          allowClear
          showSearch
          value={local.agent || undefined}
          onChange={(v) => setLocal((p) => ({ ...p, agent: v || '' }))}
          filterOption={(input, opt) =>
            (opt?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }
          options={agents.map((a) => ({ label: a, value: a }))}
        />
      </div>

      <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

      {/* ── Score range ─────────────────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          SCORE (/10)
        </Text>
        <Space size={4}>
          <InputNumber
            size="small"
            min={0}
            max={local.score_max}
            step={0.5}
            value={local.score_min}
            onChange={(v) => setLocal((p) => ({ ...p, score_min: v ?? 0 }))}
            style={{ width: 60 }}
            placeholder="Min"
          />
          <Text type="secondary">–</Text>
          <InputNumber
            size="small"
            min={local.score_min}
            max={10}
            step={0.5}
            value={local.score_max}
            onChange={(v) => setLocal((p) => ({ ...p, score_max: v ?? 10 }))}
            style={{ width: 60 }}
            placeholder="Max"
          />
        </Space>
        <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
          {[
            { label: '< 5', min: 0, max: 5 },
            { label: '5–7', min: 5, max: 7 },
            { label: '7–9', min: 7, max: 9 },
            { label: '9+', min: 9, max: 10 },
          ].map((r) => (
            <Tag
              key={r.label}
              style={{ cursor: 'pointer', fontSize: 11, padding: '0 5px', margin: 0 }}
              color={local.score_min === r.min && local.score_max === r.max ? 'blue' : undefined}
              onClick={() => setLocal((p) => ({ ...p, score_min: r.min, score_max: r.max }))}
            >
              {r.label}
            </Tag>
          ))}
        </div>
      </div>

      <Divider type="vertical" style={{ height: 44, margin: '0 4px' }} />

      {/* ── Chat link / session_id ──────────────────────────────────── */}
      <div>
        <Text style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
          LINK ĐOẠN CHAT
        </Text>
        <Input
          size="small"
          prefix={<LinkOutlined style={{ color: '#bbb' }} />}
          placeholder="Dán link Crisp hoặc session_id…"
          value={local.chat_link}
          onChange={(e) => setLocal((p) => ({ ...p, chat_link: e.target.value }))}
          onPressEnter={apply}
          allowClear
          style={{ width: 260 }}
        />
      </div>

      {/* ── Buttons ─────────────────────────────────────────────────── */}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={reset}
          style={{ color: '#888' }}
        >
          Reset
        </Button>
        <Button
          type="primary"
          size="small"
          icon={<FilterOutlined />}
          onClick={apply}
          style={{ minWidth: 90 }}
        >
          Filter{activeCount > 0 ? ` (${activeCount})` : ''}
        </Button>
      </div>
    </div>
  )
}
