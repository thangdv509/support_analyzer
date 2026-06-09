import { useMemo, useState } from 'react'
import {
  Avatar, Button, DatePicker, Divider, Progress, Table, Tag, Typography,
} from 'antd'
import { FilterOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import axios from 'axios'

const { RangePicker } = DatePicker
const { Text }        = Typography

const http = axios.create({ baseURL: '/api', withCredentials: true })

interface AgentStat {
  email:       string
  total_count: number
  total_point: number
  by_role:     { mentioned: number; cs1: number; cs2: number; tech: number }
}

interface UserInfo { email: string; name: string; nickname: string; picture: string }

async function fetchReviewStats(dateFrom='', dateTo=''): Promise<AgentStat[]> {
  const params = new URLSearchParams()
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo)   params.set('date_to',   dateTo)
  return (await http.get(`/review-stats?${params}`)).data
}

async function fetchAllUsers(): Promise<UserInfo[]> {
  return (await http.get('/users')).data
}

const PRESETS: { label: string; range: () => [Dayjs, Dayjs] }[] = [
  { label: 'Hôm qua',     range: () => [dayjs().subtract(1,'day'), dayjs().subtract(1,'day')] },
  { label: 'Hôm nay',     range: () => [dayjs(), dayjs()] },
  { label: '7 ngày',      range: () => [dayjs().subtract(6,'day'), dayjs()] },
  { label: '30 ngày',     range: () => [dayjs().subtract(29,'day'), dayjs()] },
  { label: 'Tháng này',   range: () => [dayjs().startOf('month'), dayjs()] },
  { label: 'Tháng trước', range: () => [dayjs().subtract(1,'month').startOf('month'), dayjs().subtract(1,'month').endOf('month')] },
]

function pointColor(v: number) {
  if (v >= 30) return '#22c55e'
  if (v >= 15) return '#3b82f6'
  if (v >= 5)  return '#f59e0b'
  return '#94a3b8'
}

export default function ReviewStats() {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo,   setDateTo]   = useState('')
  const [dateVal,  setDateVal]  = useState<[Dayjs,Dayjs]|null>(null)
  const [applied,  setApplied]  = useState({ dateFrom:'', dateTo:'' })

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['review-stats', applied.dateFrom, applied.dateTo],
    queryFn: () => fetchReviewStats(applied.dateFrom, applied.dateTo),
    staleTime: 60_000,
  })

  const { data: allUsers = [] } = useQuery({
    queryKey: ['all-users'],
    queryFn: fetchAllUsers,
    staleTime: 10 * 60_000,
  })

  // Map email → full user info for display
  const userInfoMap = useMemo(() =>
    Object.fromEntries(allUsers.map(u => [u.email.toLowerCase(), u])),
  [allUsers])

  const userMap = useMemo(() =>
    Object.fromEntries(allUsers.map(u => [u.email.toLowerCase(), u.nickname?.trim() || u.name])),
  [allUsers])

  const maxPoint = Math.max(...rows.map(r => r.total_point), 1)

  const setDate = (range: [Dayjs,Dayjs]|null) => {
    setDateVal(range)
    setDateFrom(range?.[0]?.format('YYYY-MM-DD') || '')
    setDateTo(range?.[1]?.format('YYYY-MM-DD') || '')
  }

  const columns = [
    {
      title: '#', key:'rank', width:44,
      render: (_:unknown, __:AgentStat, idx:number) => (
        <Text type="secondary" style={{ fontSize:12 }}>{idx+1}</Text>
      ),
    },
    {
      title: 'Agent', dataIndex:'email', key:'email',
      render: (email:string) => {
        const u         = userInfoMap[email.toLowerCase()]
        const nickname  = u?.nickname?.trim() || ''
        const googleName= u?.name || email.split('@')[0]
        const displayName = nickname || googleName
        const picture   = u?.picture || ''
        return (
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            {picture
              ? <img src={picture} alt="" style={{ width:32, height:32, borderRadius:'50%', flexShrink:0 }} />
              : <Avatar size={32} icon={<UserOutlined />} style={{ flexShrink:0 }} />
            }
            <div>
              <div style={{ fontWeight:600, fontSize:13, lineHeight:1.3 }}>{displayName}</div>
              {nickname && nickname !== googleName && (
                <div style={{ fontSize:11, color:'#64748b', lineHeight:1.3 }}>{googleName}</div>
              )}
              <div style={{ fontSize:11, color:'#94a3b8', lineHeight:1.3 }}>{email}</div>
            </div>
          </div>
        )
      },
    },
    {
      title: 'Reviews', dataIndex:'total_count', key:'count', width:90,
      sorter:(a:AgentStat,b:AgentStat)=>a.total_count-b.total_count,
      render:(v:number)=><Tag style={{ fontWeight:600 }}>{v}</Tag>,
    },
    {
      title: 'Điểm tổng', dataIndex:'total_point', key:'point', width:240,
      defaultSortOrder:'descend' as const,
      sorter:(a:AgentStat,b:AgentStat)=>a.total_point-b.total_point,
      render:(v:number)=>(
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontWeight:800, fontSize:15, color:pointColor(v), minWidth:44, textAlign:'right' }}>
            {v.toFixed(1)}
          </span>
          <Progress
            percent={Math.round((v/maxPoint)*100)}
            showInfo={false}
            strokeColor={pointColor(v)}
            trailColor="#e2e8f0"
            style={{ flex:1, marginBottom:0 }}
            size={[undefined, 6] as unknown as 'small'}
          />
        </div>
      ),
    },
    {
      title: 'Vai trò', key:'roles', width:240,
      render: (r:AgentStat) => (
        <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
          {[
            { key:'mentioned', label:'Mentioned', color:'#6366f1' },
            { key:'cs1',      label:'CS 1',      color:'#0891b2' },
            { key:'cs2',      label:'CS 2',      color:'#16a34a' },
            { key:'tech',     label:'Tech',      color:'#f59e0b' },
          ].filter(role => r.by_role[role.key as keyof typeof r.by_role] > 0).map(role => (
            <span key={role.key} style={{
              background:`${role.color}18`, color:role.color,
              border:`1px solid ${role.color}33`, borderRadius:99,
              fontSize:11, fontWeight:600, padding:'0 7px',
            }}>
              {role.label}: {r.by_role[role.key as keyof typeof r.by_role]}
            </span>
          ))}
        </div>
      ),
    },
  ]

  return (
    <div>
      {/* Filter bar */}
      <div style={{
        background:'#fff', borderRadius:10, boxShadow:'0 1px 4px #0001',
        padding:'10px 16px', marginBottom:10,
        display:'flex', flexWrap:'wrap', gap:'8px 20px', alignItems:'flex-end',
      }}>
        <div>
          <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>KHOẢNG NGÀY</Text>
          <RangePicker size="small" format="DD/MM/YYYY" value={dateVal}
            onChange={v => setDate(v as [Dayjs,Dayjs]|null)}
            style={{ width:210 }} allowClear placeholder={['Từ ngày','Đến ngày']} />
          <div style={{ marginTop:4, display:'flex', gap:4, flexWrap:'wrap' }}>
            {PRESETS.map(p => (
              <Tag key={p.label}
                style={{ cursor:'pointer', fontSize:11, padding:'0 6px', margin:0 }}
                color={dateFrom === p.range()[0].format('YYYY-MM-DD') ? 'blue' : undefined}
                onClick={() => setDate(p.range())}>
                {p.label}
              </Tag>
            ))}
          </div>
        </div>

        <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

        <div style={{ display:'flex', gap:8, alignItems:'flex-end' }}>
          <Button type="primary" size="small" icon={<FilterOutlined />}
            onClick={() => setApplied({ dateFrom, dateTo })}>
            Xem
          </Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => { setDate(null); setApplied({ dateFrom:'', dateTo:'' }) }}>
            Reset
          </Button>
        </div>
      </div>

      {/* Summary */}
      {rows.length > 0 && (
        <div style={{
          background:'#fff', borderRadius:10, boxShadow:'0 1px 4px #0001',
          padding:'8px 20px', marginBottom:10,
          display:'flex', gap:20, alignItems:'center', flexWrap:'wrap',
        }}>
          {[
            { label:'Tổng agents', value: rows.length },
            { label:'Tổng điểm',  value: rows.reduce((s,r)=>s+r.total_point,0).toFixed(1) },
            { label:'Tổng reviews', value: rows.reduce((s,r)=>s+r.total_count,0) },
          ].map(item => (
            <div key={item.label} style={{ display:'flex', alignItems:'baseline', gap:6 }}>
              <Text type="secondary" style={{ fontSize:11 }}>{item.label}</Text>
              <Text strong style={{ fontSize:16 }}>{item.value}</Text>
            </div>
          ))}
          {(applied.dateFrom||applied.dateTo) && (
            <Text type="secondary" style={{ fontSize:11, marginLeft:'auto' }}>
              {applied.dateFrom||'…'} → {applied.dateTo||'now'}
            </Text>
          )}
        </div>
      )}

      {/* Table */}
      <div style={{ background:'#fff', borderRadius:10, boxShadow:'0 1px 4px #0001', overflow:'hidden' }}>
        <div style={{ padding:'10px 16px 8px', borderBottom:'1px solid #f1f5f9', display:'flex', alignItems:'center', gap:8 }}>
          <Text strong style={{ fontSize:13 }}>Review Stats by Agent</Text>
          <Text type="secondary" style={{ fontSize:11 }}>{rows.length} agents</Text>
        </div>
        <Table<AgentStat>
          dataSource={rows} columns={columns} rowKey="email"
          loading={isLoading} pagination={false} size="small" />
      </div>
    </div>
  )
}
