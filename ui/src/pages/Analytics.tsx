import { useMemo, useState } from 'react'
import { Card, DatePicker, Segmented, Select, Spin, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import dayjs, { type Dayjs } from 'dayjs'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, Treemap, Cell,
} from 'recharts'

const { RangePicker } = DatePicker
const { Text, Title } = Typography

const APP_COLOR: Record<string, string> = { DECO: '#0e7490', SearchPie: '#7c3aed' }

const AGENT_PALETTE = [
  '#6366f1','#0891b2','#059669','#d97706','#dc2626',
  '#7c3aed','#db2777','#2563eb','#0d9488','#16a34a',
  '#7c2d12','#4338ca','#0369a1','#166534','#92400e',
]

const PRESETS: { label: string; days: number }[] = [
  { label: 'Tất cả', days: 0 },
  { label: '30 ngày', days: 30 },
  { label: '3 tháng', days: 90 },
  { label: '6 tháng', days: 180 },
  { label: '1 năm', days: 365 },
]

// Color scales per app: [empty, l1, l2, l3, l4]
const HEAT_SCALE: Record<string, string[]> = {
  All:       ['#ebedf0', '#c7d2fe', '#818cf8', '#4338ca', '#1e1b4b'],
  DECO:      ['#ebedf0', '#a5f3fc', '#22d3ee', '#0891b2', '#155e75'],
  SearchPie: ['#ebedf0', '#ddd6fe', '#a78bfa', '#6d28d9', '#3b0764'],
}

interface TimePt {
  date: string; total: number; DECO: number; SearchPie: number
  avg_score: number | null
}

interface AgentRow {
  agent: string; count: number; avg_score: number | null
  DECO: number; SearchPie: number
}

interface DowRow  { day: string; count: number; DECO: number; SearchPie: number }
interface ScoreRow { range: string; count: number; DECO: number; SearchPie: number }

interface AnalyticsData {
  total: number
  avg_score: number | null
  by_app: Record<string, number>
  time_series: TimePt[]
  by_agent: AgentRow[]
  by_day_of_week: DowRow[]
  score_distribution: ScoreRow[]
}

// ── Calendar Heatmap ───────────────────────────────────────────────────────

interface CalProps {
  timeSeries: TimePt[]
  appFilter: string
}

function CalendarHeatmap({ timeSeries, appFilter }: CalProps) {
  const [hov, setHov] = useState<{ date: string; count: number; sx: number; sy: number } | null>(null)

  const lookup = useMemo(() => {
    const m: Record<string, TimePt> = {}
    for (const pt of timeSeries) m[pt.date] = pt
    return m
  }, [timeSeries])

  const sortedDates = useMemo(() => Object.keys(lookup).sort(), [lookup])

  if (sortedDates.length === 0) {
    return (
      <div style={{ height: 110, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 13 }}>
        Không có dữ liệu
      </div>
    )
  }

  const getCount = (pt: TimePt | undefined) => {
    if (!pt) return 0
    if (appFilter === 'DECO') return pt.DECO
    if (appFilter === 'SearchPie') return pt.SearchPie
    return pt.total
  }

  const maxCount = Math.max(...sortedDates.map(d => getCount(lookup[d])), 1)
  const scale = HEAT_SCALE[appFilter] ?? HEAT_SCALE.All

  const cellColor = (count: number) => {
    if (count === 0) return scale[0]
    const r = count / maxCount
    if (r < 0.20) return scale[1]
    if (r < 0.45) return scale[2]
    if (r < 0.75) return scale[3]
    return scale[4]
  }

  // Compute grid bounds: Monday of first-date's week → Sunday of last-date's week
  const toMonday = (d: Dayjs) => {
    const dow = d.day()                 // 0=Sun..6=Sat
    return d.subtract(dow === 0 ? 6 : dow - 1, 'day')
  }
  const startDay = toMonday(dayjs(sortedDates[0]))
  const endDay   = (() => {
    const d = dayjs(sortedDates[sortedDates.length - 1])
    const dow = d.day()
    return dow === 0 ? d : d.add(7 - dow, 'day')
  })()
  const numWeeks = Math.ceil((endDay.diff(startDay, 'day') + 1) / 7)

  const CELL = 18, GAP = 3, STEP = CELL + GAP
  const LEFT = 28, TOP = 20

  // Month labels (first week of each month)
  const monthLabels: { label: string; wi: number }[] = []
  let lastM = -1
  for (let wi = 0; wi < numWeeks; wi++) {
    const m = startDay.add(wi * 7, 'day').month()
    if (m !== lastM) {
      monthLabels.push({ label: startDay.add(wi * 7, 'day').format('MMM'), wi })
      lastM = m
    }
  }

  const DAY_LABELS = ['M', '', 'W', '', 'F', '', 'S']
  const svgW = LEFT + numWeeks * STEP + 4
  const svgH = TOP + 7 * STEP

  return (
    <div style={{ overflowX: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={svgW} height={svgH} style={{ display: 'block' }}
        onMouseLeave={() => setHov(null)}>

        {/* Month labels */}
        {monthLabels.map(({ label, wi }) => (
          <text key={`${label}-${wi}`} x={LEFT + wi * STEP} y={12} fontSize={10} fill="#64748b">{label}</text>
        ))}

        {/* Day labels */}
        {DAY_LABELS.map((lbl, di) => (
          <text key={di} x={LEFT - 4} y={TOP + di * STEP + CELL - 1}
            fontSize={9} fill="#94a3b8" textAnchor="end">{lbl}</text>
        ))}

        {/* Cells */}
        {Array.from({ length: numWeeks }, (_, wi) =>
          Array.from({ length: 7 }, (_, di) => {
            const date  = startDay.add(wi * 7 + di, 'day').format('YYYY-MM-DD')
            const pt    = lookup[date]
            const count = getCount(pt)
            const sx    = LEFT + wi * STEP
            const sy    = TOP + di * STEP
            return (
              <rect key={date} x={sx} y={sy} width={CELL} height={CELL}
                fill={cellColor(count)} rx={2}
                style={{ cursor: 'default' }}
                onMouseEnter={() => setHov({ date, count, sx: sx + CELL / 2, sy })}
              />
            )
          })
        )}

        {/* SVG Tooltip — flip below cell when near top edge */}
        {hov && (() => {
          const txt = `${hov.date}: ${hov.count} chats`
          const tw  = txt.length * 6.2 + 16
          const tx  = Math.max(4, Math.min(hov.sx - tw / 2, svgW - tw - 4))
          const above = hov.sy > TOP + 22
          const ty  = above ? hov.sy - 26 : hov.sy + CELL + 4
          return (
            <g style={{ pointerEvents: 'none' }}>
              <rect x={tx} y={ty} width={tw} height={19} fill="#1e293b" rx={3} />
              <text x={tx + tw / 2} y={ty + 13} fill="#fff" fontSize={10} textAnchor="middle">{txt}</text>
            </g>
          )
        })()}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 6, fontSize: 10, color: '#94a3b8' }}>
        <span>Ít</span>
        {scale.map((c, i) => (
          <div key={i} style={{ width: CELL, height: CELL, background: c, borderRadius: 2 }} />
        ))}
        <span>Nhiều</span>
      </div>
    </div>
  )
}

// ── Day × Hour heatmap ────────────────────────────────────────────────────

interface HeatmapData { grid: number[][]; total: number }

function ChatHeatmap({ grid, appFilter }: { grid: number[][], appFilter: string }) {
  const [hov, setHov] = useState<{ d: number; h: number; count: number; sx: number; sy: number } | null>(null)

  const DAYS  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const scale = HEAT_SCALE[appFilter] ?? HEAT_SCALE.All
  const maxV  = Math.max(...grid.flat(), 1)

  const cellColor = (v: number) => {
    if (v === 0) return scale[0]
    const r = v / maxV
    if (r < 0.20) return scale[1]
    if (r < 0.45) return scale[2]
    if (r < 0.75) return scale[3]
    return scale[4]
  }

  const CW = 28, CH = 26, GAP = 3
  const CSTEP = CW + GAP, RSTEP = CH + GAP
  const LEFT = 36, TOP = 20
  const svgW = LEFT + 24 * CSTEP
  const svgH = TOP + 7 * RSTEP + 6

  return (
    <div style={{ overflowX: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={svgW} height={svgH} style={{ display: 'block' }}
        onMouseLeave={() => setHov(null)}>

        {/* Hour labels every 3h */}
        {Array.from({ length: 24 }, (_, h) => h % 3 === 0 && (
          <text key={h} x={LEFT + h * CSTEP + CW / 2} y={12}
            fontSize={9} fill="#64748b" textAnchor="middle">{h}h</text>
        ))}

        {/* Day labels */}
        {DAYS.map((d, di) => (
          <text key={di} x={LEFT - 4} y={TOP + di * RSTEP + CH - 3}
            fontSize={10} fill="#64748b" textAnchor="end">{d}</text>
        ))}

        {/* Cells */}
        {grid.map((row, di) => row.map((count, hi) => {
          const sx = LEFT + hi * CSTEP
          const sy = TOP + di * RSTEP
          return (
            <rect key={`${di}-${hi}`} x={sx} y={sy} width={CW} height={CH}
              fill={cellColor(count)} rx={2} style={{ cursor: 'default' }}
              onMouseEnter={() => setHov({ d: di, h: hi, count, sx: sx + CW / 2, sy })}
            />
          )
        }))}

        {/* SVG Tooltip — flip below cell when near top edge */}
        {hov && (() => {
          const txt = `${DAYS[hov.d]}, ${hov.h}h: ${hov.count} chats`
          const tw  = txt.length * 6.2 + 16
          const tx  = Math.max(4, Math.min(hov.sx - tw / 2, svgW - tw - 4))
          const above = hov.sy > TOP + CH + 2
          const ty  = above ? hov.sy - 26 : hov.sy + CH + 4
          return (
            <g style={{ pointerEvents: 'none' }}>
              <rect x={tx} y={ty} width={tw} height={19} fill="#1e293b" rx={3} />
              <text x={tx + tw / 2} y={ty + 13} fill="#fff" fontSize={10} textAnchor="middle">{txt}</text>
            </g>
          )
        })()}
      </svg>

      <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 6, fontSize: 10, color: '#94a3b8' }}>
        <span>Ít</span>
        {scale.map((c, i) => <div key={i} style={{ width: 14, height: 14, background: c, borderRadius: 2 }} />)}
        <span>Nhiều</span>
      </div>
    </div>
  )
}

// ── Treemap custom cell ────────────────────────────────────────────────────

function MapCell(props: Record<string, unknown>) {
  const { x, y, width, height, name, value, fill } = props as {
    x: number; y: number; width: number; height: number
    name: string; value: number; fill: string
  }
  if (value == null || (width as number) < 20 || (height as number) < 15) return null
  const w = width as number, h = height as number
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill={fill} rx={3} stroke="#fff" strokeWidth={2} />
      {w > 55 && h > 26 && (
        <text x={(x as number) + 8} y={(y as number) + 18} fill="#fff" fontSize={12} fontWeight={700}
          style={{ pointerEvents: 'none' }}>
          {(name as string).length > 15 ? (name as string).slice(0, 14) + '…' : name}
        </text>
      )}
      {w > 55 && h > 42 && (
        <text x={(x as number) + 8} y={(y as number) + 32} fill="rgba(255,255,255,0.8)" fontSize={11}
          style={{ pointerEvents: 'none' }}>
          {value} chats
        </text>
      )}
    </g>
  )
}

// ── Score color ────────────────────────────────────────────────────────────
function sc(v: number | null) {
  if (v == null) return '#94a3b8'
  if (v >= 9)   return '#16a34a'
  if (v >= 7.5) return '#2563eb'
  if (v >= 5)   return '#d97706'
  return '#dc2626'
}

// ── Main component ─────────────────────────────────────────────────────────

export default function Analytics() {
  const [appFilter, setAppFilter]     = useState('All')
  const [groupBy, setGroupBy]         = useState('month')
  const [preset, setPreset]           = useState(0)
  const [dateRange, setDateRange]     = useState<[Dayjs | null, Dayjs | null]>([null, null])
  const [heatmapMode, setHeatmapMode] = useState<'calendar' | 'hourly'>('calendar')

  const applyPreset = (days: number) => {
    setPreset(days)
    setDateRange(days === 0 ? [null, null] : [dayjs().subtract(days, 'day'), dayjs()])
  }

  const dateFrom = dateRange[0]?.format('YYYY-MM-DD') ?? ''
  const dateTo   = dateRange[1]?.format('YYYY-MM-DD') ?? ''

  // Main query (grouped by groupBy for trend chart)
  const { data, isFetching } = useQuery<AnalyticsData>({
    queryKey: ['analytics', appFilter, groupBy, dateFrom, dateTo],
    queryFn: async () => {
      const p = new URLSearchParams({ group_by: groupBy })
      if (dateFrom) p.set('date_from', dateFrom)
      if (dateTo)   p.set('date_to', dateTo)
      if (appFilter !== 'All') p.set('app', appFilter)
      return (await axios.get(`/api/analytics?${p}`)).data
    },
    staleTime: 3 * 60_000,
  })

  // Day×hour heatmap query (sumtag.end_session)
  const { data: heatmapData } = useQuery<HeatmapData>({
    queryKey: ['heatmap', appFilter, dateFrom, dateTo],
    queryFn: async () => {
      const p = new URLSearchParams()
      if (dateFrom) p.set('date_from', dateFrom)
      if (dateTo)   p.set('date_to', dateTo)
      if (appFilter !== 'All') p.set('app', appFilter)
      return (await axios.get(`/api/heatmap?${p}`)).data
    },
    staleTime: 5 * 60_000,
  })

  // Daily query for calendar heatmap (only when not already daily)
  const { data: dailyData } = useQuery<AnalyticsData>({
    queryKey: ['analytics-daily', appFilter, dateFrom, dateTo],
    queryFn: async () => {
      const p = new URLSearchParams({ group_by: 'day' })
      if (dateFrom) p.set('date_from', dateFrom)
      if (dateTo)   p.set('date_to', dateTo)
      if (appFilter !== 'All') p.set('app', appFilter)
      return (await axios.get(`/api/analytics?${p}`)).data
    },
    enabled: groupBy !== 'day',
    staleTime: 5 * 60_000,
  })

  const calendarSeries: TimePt[] = useMemo(
    () => groupBy === 'day' ? (data?.time_series ?? []) : (dailyData?.time_series ?? []),
    [groupBy, data, dailyData]
  )

  const treemapData = useMemo(() =>
    (data?.by_agent ?? []).filter(a => a.count > 0).map((a, i) => ({
      name: a.agent, size: a.count,
      fill: AGENT_PALETTE[i % AGENT_PALETTE.length],
    })),
  [data])

  const timeSeriesChart = useMemo(() =>
    (data?.time_series ?? []).map(pt => ({
      date: pt.date, total: pt.total, DECO: pt.DECO, SearchPie: pt.SearchPie,
    })),
  [data])

  const showSplit    = appFilter === 'All'
  const tooltipFmt   = (v: unknown) => (v == null ? '—' : String(v))

  return (
    <div style={{ paddingBottom: 32 }}>

      {/* ── Header controls ──────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        background: '#fff', padding: '10px 16px', borderRadius: 12,
        border: '1px solid #e2e8f0', marginBottom: 16,
      }}>
        <div style={{ flex: 1, minWidth: 140 }}>
          <Title level={5} style={{ margin: 0, color: '#0f172a', fontSize: 14 }}>📊 Analytics</Title>
          <Text style={{ fontSize: 11, color: '#94a3b8' }}>
            {dateRange[0] && dateRange[1]
              ? `${dateRange[0].format('DD/MM/YYYY')} – ${dateRange[1].format('DD/MM/YYYY')}`
              : 'Tất cả thời gian'}
          </Text>
        </div>

        <Segmented size="small" value={appFilter} onChange={v => setAppFilter(v as string)}
          options={[
            { label: 'Tất cả', value: 'All' },
            { label: 'DECO',      value: 'DECO' },
            { label: 'SearchPie', value: 'SearchPie' },
          ]}
        />

        <Select size="small" value={groupBy} onChange={setGroupBy} style={{ width: 130 }}
          options={[
            { label: 'Theo ngày',  value: 'day' },
            { label: 'Theo tháng', value: 'month' },
            { label: 'Theo năm',   value: 'year' },
          ]}
        />

        <div style={{ display: 'flex', gap: 4 }}>
          {PRESETS.map(p => (
            <button key={p.days} onClick={() => applyPreset(p.days)} style={{
              padding: '2px 9px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: '1px solid',
              background:  preset === p.days ? '#6366f1' : '#f8fafc',
              color:       preset === p.days ? '#fff'    : '#64748b',
              borderColor: preset === p.days ? '#6366f1' : '#e2e8f0',
              fontWeight: 500,
            }}>{p.label}</button>
          ))}
        </div>

        <RangePicker size="small" value={dateRange as [Dayjs, Dayjs] | null}
          onChange={v => {
            if (v?.[0] && v[1]) { setDateRange([v[0], v[1]]); setPreset(-1) }
            else { setDateRange([null, null]); setPreset(0) }
          }}
        />
      </div>

      {isFetching && <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>}

      {data && !isFetching && (
        <>
          {/* ── Summary cards ────────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Tổng QA chats', value: (data.total ?? 0).toLocaleString(), color: '#6366f1' },
              { label: 'Avg score',     value: data.avg_score?.toFixed(2) ?? '—',  color: sc(data.avg_score) },
              { label: 'DECO',          value: (data.by_app?.DECO ?? 0).toLocaleString(),       color: APP_COLOR.DECO },
              { label: 'SearchPie',     value: (data.by_app?.SearchPie ?? 0).toLocaleString(),  color: APP_COLOR.SearchPie },
            ].map(c => (
              <Card key={c.label} style={{ flex: 1, textAlign: 'center' }} styles={{ body: { padding: '14px 12px' } }}>
                <div style={{ fontSize: 10, color: '#94a3b8', fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase' }}>{c.label}</div>
                <div style={{ fontSize: 26, fontWeight: 800, color: c.color, lineHeight: 1.25, marginTop: 2 }}>{c.value}</div>
              </Card>
            ))}
          </div>

          {/* ── Trend chart ───────────────────────────────────────────────── */}
          <Card style={{ marginBottom: 16 }} styles={{ body: { paddingTop: 8, paddingBottom: 8 } }}
            title={<span style={{ fontSize: 13, fontWeight: 600 }}>Chats theo thời gian</span>}>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={timeSeriesChart} margin={{ top: 4, right: 16, bottom: 0, left: -10 }}>
                <defs>
                  <linearGradient id="gDECO" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={APP_COLOR.DECO}      stopOpacity={0.3} />
                    <stop offset="95%" stopColor={APP_COLOR.DECO}      stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gSP" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={APP_COLOR.SearchPie} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={APP_COLOR.SearchPie} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gAll" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <RTooltip contentStyle={{ fontSize: 11 }} formatter={tooltipFmt} />
                <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                {showSplit ? (
                  <>
                    <Area type="monotone" dataKey="DECO"      stroke={APP_COLOR.DECO}      fill="url(#gDECO)" strokeWidth={2} dot={false} />
                    <Area type="monotone" dataKey="SearchPie" stroke={APP_COLOR.SearchPie} fill="url(#gSP)"   strokeWidth={2} dot={false} />
                  </>
                ) : (
                  <Area type="monotone" dataKey="total" stroke="#6366f1" fill="url(#gAll)" strokeWidth={2} dot={false} name="Chats" />
                )}
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          {/* ── Combined heatmap card ────────────────────────────────────── */}
          <Card style={{ marginBottom: 16 }}
            styles={{ body: { paddingTop: 10 } }}
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Mật độ chat</span>
                <Segmented
                  size="small"
                  value={heatmapMode}
                  onChange={v => setHeatmapMode(v as 'calendar' | 'hourly')}
                  options={[
                    { label: 'Theo ngày', value: 'calendar' },
                    { label: 'Theo giờ',  value: 'hourly' },
                  ]}
                />
              </div>
            }>
            {heatmapMode === 'calendar'
              ? <CalendarHeatmap timeSeries={calendarSeries} appFilter={appFilter} />
              : heatmapData && heatmapData.total > 0
                ? <ChatHeatmap grid={heatmapData.grid} appFilter={appFilter} />
                : <div style={{ height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 13 }}>Không có dữ liệu</div>
            }
          </Card>

          {/* ── Treemap + Score distribution ────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16 }}>

            <Card styles={{ body: { padding: '8px 12px' } }}
              title={<span style={{ fontSize: 13, fontWeight: 600 }}>Phân bổ theo nhân viên</span>}>
              {treemapData.length > 0 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <Treemap data={treemapData} dataKey="size" content={<MapCell />}>
                    {treemapData.map((_, i) => (
                      <Cell key={i} fill={AGENT_PALETTE[i % AGENT_PALETTE.length]} />
                    ))}
                  </Treemap>
                </ResponsiveContainer>
              ) : (
                <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 13 }}>
                  Không có dữ liệu
                </div>
              )}
            </Card>

            <Card styles={{ body: { padding: '8px 12px 12px' } }}
              title={<span style={{ fontSize: 13, fontWeight: 600 }}>Phân bổ điểm QA</span>}>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={data.score_distribution} margin={{ top: 4, right: 8, bottom: 0, left: -14 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="range" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <RTooltip contentStyle={{ fontSize: 11 }} formatter={tooltipFmt} />
                  <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                  {showSplit ? (
                    <>
                      <Bar dataKey="DECO"      stackId="s" fill={APP_COLOR.DECO}      />
                      <Bar dataKey="SearchPie" stackId="s" fill={APP_COLOR.SearchPie} radius={[4,4,0,0]} />
                    </>
                  ) : (
                    <Bar dataKey="count" fill="#6366f1" radius={[4,4,0,0]} name="Chats" />
                  )}
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
