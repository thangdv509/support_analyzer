import { useMemo, useState } from 'react'
import {
  Avatar, DatePicker, Divider, Empty, Progress, Segmented, Spin, Tag, Typography,
} from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import dayjs, { type Dayjs } from 'dayjs'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'
import { useAuth } from '../context/AuthContext'

const http = axios.create({ baseURL: '/api', withCredentials: true })
const { Text } = Typography
const { RangePicker } = DatePicker

// ── Constants ─────────────────────────────────────────────────────────────────

const APP_COLOR: Record<string, string> = { SearchPie: '#7c3aed', DECO: '#0e7490' }
const ROLE_COLOR: Record<string, string> = {
  mentioned: '#6366f1', cs1: '#0891b2', cs2: '#16a34a', tech: '#f59e0b',
}
const SCORE_COLOR = (v: number | null) => {
  if (v == null) return '#94a3b8'
  if (v >= 9)   return '#22c55e'
  if (v >= 7.5) return '#3b82f6'
  if (v >= 5)   return '#f59e0b'
  return '#ef4444'
}

const PRESETS: { label: string; range: () => [Dayjs, Dayjs] }[] = [
  { label: '30 ngày',     range: () => [dayjs().subtract(29, 'day'), dayjs()] },
  { label: '3 tháng',     range: () => [dayjs().subtract(3, 'month').startOf('month'), dayjs()] },
  { label: '6 tháng',     range: () => [dayjs().subtract(6, 'month').startOf('month'), dayjs()] },
  { label: 'Năm này',     range: () => [dayjs().startOf('year'), dayjs()] },
  { label: 'Năm trước',   range: () => [dayjs().subtract(1,'year').startOf('year'), dayjs().subtract(1,'year').endOf('year')] },
]

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserInfo { email: string; name: string; nickname: string; picture: string; role: string }
interface AgentRow { email: string; nickname: string; name: string; picture: string
  qaCount: number; qaAvg: number | null; reviewCount: number; reviewPoint: number
  byRole: Record<string, number>
}

// ── API ───────────────────────────────────────────────────────────────────────

const fetchAgentMap = () => http.get('/users/agent-map').then(r => r.data as Record<string, UserInfo>)
const fetchQAStats  = () => http.get('/stats').then(r => r.data)
const fetchRevStats = () => http.get('/review-stats').then(r => r.data as {
  email: string; total_count: number; total_point: number; by_role: Record<string,number>
}[])

const fetchQATrend = (nickname: string, groupBy: string, df: string, dt: string) => {
  const p = new URLSearchParams({ agent: nickname, group_by: groupBy })
  if (df) p.set('date_from', df)
  if (dt) p.set('date_to', dt)
  return http.get(`/qa-score-trend?${p}`).then(r => r.data as {date:string;avg_score:number;count:number}[])
}

const fetchRevTrend = (email: string, groupBy: string, df: string, dt: string) => {
  const p = new URLSearchParams({ agent: email, group_by: groupBy })
  if (df) p.set('date_from', df)
  if (dt) p.set('date_to', dt)
  return http.get(`/review-trend?${p}`).then(r => r.data as { data: Record<string,unknown>[]; apps: string[] })
}

// ── Left panel — agent list ───────────────────────────────────────────────────

function AgentListItem({ row, selected, onClick }: { row: AgentRow; selected: boolean; onClick: () => void }) {
  const color = SCORE_COLOR(row.qaAvg)
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 14px', cursor: 'pointer', transition: 'background .15s',
      background: selected ? '#6366f108' : 'transparent',
      borderLeft: selected ? '3px solid #6366f1' : '3px solid transparent',
      borderBottom: '1px solid #f1f5f9',
    }}>
      {row.picture
        ? <img src={row.picture} alt="" style={{ width:36, height:36, borderRadius:'50%', flexShrink:0 }} />
        : <Avatar size={36} icon={<UserOutlined />} style={{ flexShrink:0, background:'#e2e8f0', color:'#64748b' }} />
      }
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight:600, fontSize:13, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
          {row.nickname || row.name}
        </div>
        <div style={{ display:'flex', gap:8, marginTop:2 }}>
          {row.qaAvg != null && (
            <span style={{ fontSize:11, fontWeight:700, color }}>QA {row.qaAvg.toFixed(1)}</span>
          )}
          {row.reviewCount > 0 && (
            <span style={{ fontSize:11, color:'#64748b' }}>⭐ {row.reviewCount}</span>
          )}
        </div>
      </div>
      {row.qaAvg != null && (
        <div style={{
          fontSize:13, fontWeight:800, color,
          background:`${color}14`, borderRadius:6, padding:'2px 8px', flexShrink:0,
        }}>{row.qaAvg.toFixed(1)}</div>
      )}
    </div>
  )
}

// ── Summary card ─────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label:string; value:string|number; sub?:string; color?:string }) {
  return (
    <div style={{
      background:'#fff', borderRadius:10, padding:'12px 18px',
      boxShadow:'0 1px 4px #0001', border:'1px solid #e2e8f0', flex:1, minWidth:120,
    }}>
      <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:2 }}>{label}</Text>
      <span style={{ fontWeight:800, fontSize:22, color: color||'#0f172a', letterSpacing:-0.5 }}>{value}</span>
      {sub && <Text type="secondary" style={{ fontSize:11, marginLeft:4 }}>{sub}</Text>}
    </div>
  )
}

// ── Right panel — agent detail ────────────────────────────────────────────────

function AgentDetail({ row }: { row: AgentRow }) {
  const [groupBy, setGroupBy] = useState<'day'|'month'|'year'>('month')
  const [range, setRange] = useState<[Dayjs,Dayjs]|null>([
    dayjs().subtract(5,'month').startOf('month'), dayjs(),
  ])

  const df = range?.[0]?.format('YYYY-MM-DD') || ''
  const dt = range?.[1]?.format('YYYY-MM-DD') || ''

  const { data: qaTrend = [], isFetching: qaLoading } = useQuery({
    queryKey: ['qa-trend', row.nickname, groupBy, df, dt],
    queryFn: () => fetchQATrend(row.nickname, groupBy, df, dt),
    staleTime: 60_000,
    enabled: !!row.nickname,
  })

  const { data: revTrend, isFetching: revLoading } = useQuery({
    queryKey: ['rev-trend', row.email, groupBy, df, dt],
    queryFn: () => fetchRevTrend(row.email, groupBy, df, dt),
    staleTime: 60_000,
    enabled: !!row.email,
  })

  const revChartData = revTrend?.data || []
  const revApps = revTrend?.apps || []

  const roleData = [
    { role: 'Mentioned', count: row.byRole.mentioned || 0, color: ROLE_COLOR.mentioned },
    { role: 'CS 1',      count: row.byRole.cs1 || 0,       color: ROLE_COLOR.cs1 },
    { role: 'CS 2',      count: row.byRole.cs2 || 0,       color: ROLE_COLOR.cs2 },
    { role: 'Tech',      count: row.byRole.tech || 0,      color: ROLE_COLOR.tech },
  ].filter(r => r.count > 0)

  return (
    <div style={{ flex:1, overflowY:'auto', padding:'16px 20px', minWidth:0 }}>
      {/* Agent header */}
      <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:16 }}>
        {row.picture
          ? <img src={row.picture} alt="" style={{ width:52, height:52, borderRadius:'50%' }} />
          : <Avatar size={52} icon={<UserOutlined />} />
        }
        <div>
          <div style={{ fontWeight:700, fontSize:18, color:'#0f172a' }}>{row.nickname || row.name}</div>
          {row.nickname && row.nickname !== row.name &&
            <div style={{ fontSize:12, color:'#64748b' }}>{row.name}</div>}
          <div style={{ fontSize:12, color:'#94a3b8' }}>{row.email}</div>
        </div>
        {row.qaAvg != null && (
          <div style={{ marginLeft:'auto', textAlign:'center' }}>
            <div style={{ fontWeight:800, fontSize:28, color:SCORE_COLOR(row.qaAvg), letterSpacing:-1 }}>
              {row.qaAvg.toFixed(2)}
            </div>
            <Text type="secondary" style={{ fontSize:11 }}>QA avg /10</Text>
          </div>
        )}
      </div>

      {/* Summary cards */}
      <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
        <StatCard label="QA Chats" value={row.qaCount.toLocaleString()} />
        <StatCard label="QA Avg Score" value={row.qaAvg != null ? row.qaAvg.toFixed(2) : '—'} sub="/10"
          color={SCORE_COLOR(row.qaAvg)} />
        <StatCard label="Reviews (Live)" value={row.reviewCount} />
        <StatCard label="Điểm tích lũy" value={row.reviewPoint.toFixed(1)} color="#6366f1" />
      </div>

      {/* Time controls */}
      <div style={{
        background:'#fff', borderRadius:10, padding:'10px 14px', marginBottom:16,
        boxShadow:'0 1px 4px #0001', display:'flex', gap:16, alignItems:'flex-end', flexWrap:'wrap',
      }}>
        <div>
          <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>KHOẢNG NGÀY</Text>
          <RangePicker size="small" format="DD/MM/YYYY" value={range}
            onChange={v => setRange(v as [Dayjs,Dayjs]|null)} style={{ width:220 }} allowClear />
          <div style={{ marginTop:4, display:'flex', gap:4, flexWrap:'wrap' }}>
            {PRESETS.map(p => (
              <Tag key={p.label} style={{ cursor:'pointer', fontSize:10, padding:'0 5px', margin:0 }}
                color={df === p.range()[0].format('YYYY-MM-DD') ? 'blue' : undefined}
                onClick={() => setRange(p.range())}>
                {p.label}
              </Tag>
            ))}
          </div>
        </div>
        <div>
          <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>NHÓM THEO</Text>
          <Segmented size="small" value={groupBy} onChange={v => setGroupBy(v as typeof groupBy)}
            options={[{ label:'Ngày', value:'day' }, { label:'Tháng', value:'month' }, { label:'Năm', value:'year' }]}
          />
        </div>
      </div>

      {/* Charts grid */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>

        {/* QA Score trend */}
        <div style={{ background:'#fff', borderRadius:10, padding:'14px 16px', boxShadow:'0 1px 4px #0001' }}>
          <Text strong style={{ fontSize:12, display:'block', marginBottom:10 }}>QA Score theo thời gian</Text>
          {qaLoading ? <div style={{height:200,display:'flex',alignItems:'center',justifyContent:'center'}}><Spin size="small"/></div>
          : qaTrend.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{margin:'30px 0'}} description="Không có dữ liệu" />
          : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={qaTrend} margin={{ top:4, right:8, left:-20, bottom:4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize:10 }} />
                <YAxis domain={[0, 10]} tick={{ fontSize:10 }} />
                <RTooltip contentStyle={{ fontSize:11 }}
                  formatter={(v: unknown) => [`${(v as number).toFixed(2)} /10`, 'Avg score']} />
                <Line type="monotone" dataKey="avg_score" stroke="#6366f1"
                  strokeWidth={2} dot={{ r:3 }} activeDot={{ r:5 }} name="Avg score" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Review count trend */}
        <div style={{ background:'#fff', borderRadius:10, padding:'14px 16px', boxShadow:'0 1px 4px #0001' }}>
          <Text strong style={{ fontSize:12, display:'block', marginBottom:10 }}>Reviews theo thời gian</Text>
          {revLoading ? <div style={{height:200,display:'flex',alignItems:'center',justifyContent:'center'}}><Spin size="small"/></div>
          : revChartData.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{margin:'30px 0'}} description="Không có dữ liệu" />
          : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={revChartData as Record<string,unknown>[]} margin={{ top:4, right:8, left:-20, bottom:4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize:10 }} />
                <YAxis allowDecimals={false} tick={{ fontSize:10 }} />
                <RTooltip contentStyle={{ fontSize:11 }} />
                <Legend iconType="circle" wrapperStyle={{ fontSize:11 }} />
                {revApps.map(a => (
                  <Line key={a} type="monotone" dataKey={a}
                    stroke={APP_COLOR[a] || '#6366f1'} strokeWidth={2}
                    dot={{ r:3 }} activeDot={{ r:5 }} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* QA chat count bar */}
        {qaTrend.length > 0 && (
          <div style={{ background:'#fff', borderRadius:10, padding:'14px 16px', boxShadow:'0 1px 4px #0001' }}>
            <Text strong style={{ fontSize:12, display:'block', marginBottom:10 }}>Số chats QA theo kỳ</Text>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={qaTrend} margin={{ top:4, right:8, left:-20, bottom:4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize:10 }} />
                <YAxis allowDecimals={false} tick={{ fontSize:10 }} />
                <RTooltip contentStyle={{ fontSize:11 }}
                  formatter={(v: unknown) => [v as number, 'Chats']} />
                <Bar dataKey="count" fill="#6366f1" radius={[3,3,0,0]} name="Chats" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Role breakdown */}
        {roleData.length > 0 && (
          <div style={{ background:'#fff', borderRadius:10, padding:'14px 16px', boxShadow:'0 1px 4px #0001' }}>
            <Text strong style={{ fontSize:12, display:'block', marginBottom:10 }}>Vai trò trong reviews</Text>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={roleData} layout="vertical" margin={{ top:4, right:8, left:16, bottom:4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize:10 }} />
                <YAxis type="category" dataKey="role" tick={{ fontSize:11 }} width={64} />
                <RTooltip contentStyle={{ fontSize:11 }} />
                <Bar dataKey="count" radius={[0,3,3,0]} name="Reviews">
                  {roleData.map(r => <Cell key={r.role} fill={r.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* QA Score progress bar (all-time) */}
        {row.qaAvg != null && (
          <div style={{ background:'#fff', borderRadius:10, padding:'14px 16px', boxShadow:'0 1px 4px #0001', gridColumn:'span 2' }}>
            <Text strong style={{ fontSize:12, display:'block', marginBottom:12 }}>Điểm QA tổng thể</Text>
            <div style={{ display:'flex', alignItems:'center', gap:16 }}>
              <span style={{ fontWeight:800, fontSize:32, color:SCORE_COLOR(row.qaAvg), minWidth:60, letterSpacing:-1 }}>
                {row.qaAvg.toFixed(2)}
              </span>
              <Progress
                percent={Math.round((row.qaAvg / 10) * 100)}
                showInfo={false}
                strokeColor={SCORE_COLOR(row.qaAvg)}
                trailColor="#e2e8f0"
                style={{ flex:1, marginBottom:0 }}
                strokeWidth={12}
              />
              <Text type="secondary" style={{ minWidth:32, textAlign:'right' }}>/ 10</Text>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AgentAnalysis() {
  const { user } = useAuth()
  const [selected, setSelected] = useState<string | null>(null)

  const { data: agentMap = {} } = useQuery({
    queryKey: ['agent-map'], queryFn: fetchAgentMap, staleTime: 5 * 60_000,
  })
  const { data: qaStats } = useQuery({
    queryKey: ['stats', '', '', ''], queryFn: fetchQAStats, staleTime: 5 * 60_000,
  })
  const { data: revStats = [] } = useQuery({
    queryKey: ['review-stats', '', '', ''], queryFn: fetchRevStats, staleTime: 5 * 60_000,
  })

  const revByEmail = useMemo(() =>
    Object.fromEntries(revStats.map(r => [r.email.toLowerCase(), r])),
  [revStats])

  // Build merged agent list from agentMap
  const agents = useMemo<AgentRow[]>(() => {
    const byAgent = qaStats?.by_agent || {}
    return Object.entries(agentMap)
      .map(([nickname, u]) => {
        const email = u.email.toLowerCase()
        const qa = byAgent[nickname] || { count: 0, avg_score: null }
        const rev = revByEmail[email] || { total_count: 0, total_point: 0, by_role: {} }
        return {
          nickname,
          email,
          name: u.name,
          picture: u.picture,
          qaCount:      qa.count as number,
          qaAvg:        qa.avg_score as number | null,
          reviewCount:  rev.total_count,
          reviewPoint:  rev.total_point,
          byRole:       rev.by_role || {},
        }
      })
      .filter(a => user?.role !== 'support' || a.email === user.email?.toLowerCase())
      .sort((a, b) => (b.qaAvg ?? 0) - (a.qaAvg ?? 0))
  }, [agentMap, qaStats, revByEmail, user])

  const selectedRow = agents.find(a => a.email === selected) ?? agents[0] ?? null

  return (
    <div style={{ display:'flex', height:'calc(100vh - 96px)', background:'#f8fafc', overflow:'hidden' }}>
      {/* Left sidebar */}
      <div style={{
        width:260, flexShrink:0, borderRight:'1px solid #e2e8f0',
        overflowY:'auto', background:'#fff',
      }}>
        <div style={{ padding:'10px 14px 8px', borderBottom:'1px solid #f1f5f9' }}>
          <Text strong style={{ fontSize:12, color:'#64748b', letterSpacing:0.5 }}>
            AGENTS — {agents.length}
          </Text>
        </div>
        {agents.map(row => (
          <AgentListItem
            key={row.email}
            row={row}
            selected={selected ? row.email === selected : row === agents[0]}
            onClick={() => setSelected(row.email)}
          />
        ))}
      </div>

      {/* Right content */}
      {selectedRow ? (
        <AgentDetail row={selectedRow} />
      ) : (
        <div style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center' }}>
          <Empty description="Chọn một agent để xem phân tích" />
        </div>
      )}
    </div>
  )
}
