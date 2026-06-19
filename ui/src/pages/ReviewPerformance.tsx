import { useCallback, useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
  type ICellRendererParams,
  type GetRowIdParams,
} from 'ag-grid-community'
import {
  Badge, Button, DatePicker, Divider, Form, Input, InputNumber,
  message, Modal, Select, Segmented, Space, Tag, Tabs, Tooltip, Typography,
} from 'antd'
import {
  CheckOutlined, CloseOutlined, DeleteOutlined, EditOutlined,
  FilterOutlined, PlusOutlined, ReloadOutlined, SendOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import dayjs, { type Dayjs } from 'dayjs'
import { useAuth } from '../context/AuthContext'
import { fetchAgents } from '../api'

ModuleRegistry.registerModules([AllCommunityModule])

const { Text } = Typography
const { RangePicker } = DatePicker

// ── Constants ─────────────────────────────────────────────────────────────────

const STAR_RATINGS    = ['1','2','3','4','5']
const PACKAGE_OPTIONS = ['GSC package','SEO Map Package','GMC Package','VIP Scan','Upgrade','Plus','Vip AI','Speed Plan']
const APP_OPTIONS     = ['SearchPie','DECO']
const STATUS_OPTIONS  = ['Live','Pending']
const PLAN_OPTIONS    = ['Free','Paid']

const APP_COLOR: Record<string,string> = { SearchPie: '#7c3aed', DECO: '#0e7490' }

const STATUS_COLOR: Record<string,string> = { Live: '#16a34a', Pending: '#f59e0b' }
const PLAN_COLOR:   Record<string,string>  = { Free: '#475569', Paid: '#6366f1' }

// Professional palette — no red/pink tones
const AGENT_COLORS = ['#6366f1','#0891b2','#16a34a','#7c3aed','#0f766e','#0369a1','#059669','#6d28d9','#0284c7','#047857']

const DATE_PRESETS: { label: string; range: () => [Dayjs,Dayjs] }[] = [
  { label: 'Hôm qua',     range: () => [dayjs().subtract(1,'day'), dayjs().subtract(1,'day')] },
  { label: 'Hôm nay',     range: () => [dayjs(), dayjs()] },
  { label: '7 ngày',      range: () => [dayjs().subtract(6,'day'), dayjs()] },
  { label: 'Tháng này',   range: () => [dayjs().startOf('month'), dayjs()] },
  { label: 'Tháng trước', range: () => [dayjs().subtract(1,'month').startOf('month'), dayjs().subtract(1,'month').endOf('month')] },
]

// ── Types ─────────────────────────────────────────────────────────────────────

interface Review {
  id: string; seq?: number; status: string; star: string; package: string; app: string; review_date: string
  customer_name: string; link: string; app_plan: string
  mentioned: string; cs1: string; cs2: string; tech: string
  count: number; point: number; he_so: number; notes: string; created_by: string
}

interface ReviewRequest {
  id: string; review_id: string; action: string; changes: Record<string,unknown>
  reason: string; requested_by: string; status: string
  handled_by?: string; handle_note?: string; created_at: string
}

interface Filters {
  status: string; plan: string; star: string; pkg: string; app: string; agent: string
  dateFrom: string; dateTo: string; dateRange: [Dayjs,Dayjs] | null
}

// ── API ───────────────────────────────────────────────────────────────────────

const http = axios.create({ baseURL: '/api', withCredentials: true })

// Fetch all users for name resolution
interface UserInfo { email: string; name: string; nickname: string }
const fetchAllUsers = async (): Promise<UserInfo[]> => (await http.get('/users')).data
const buildUserMap  = (users: UserInfo[]): Record<string,string> =>
  Object.fromEntries(users.map(u => [u.email.toLowerCase(), u.nickname?.trim() || u.name]))

const fetchReviews    = async (): Promise<Review[]>     => (await http.get('/reviews')).data
const createReview    = async (d: object): Promise<Review> => (await http.post('/reviews', d)).data
const updateReview    = async (id: string, d: object)   => (await http.put(`/reviews/${id}`, d)).data
const updateScore     = async (id: string, d: object)   => (await http.patch(`/reviews/${id}/score`, d)).data
const deleteReview    = async (id: string)              => { await http.delete(`/reviews/${id}`) }
const submitRequest   = async (id: string, action: string, body: object) =>
  (await http.post(`/reviews/${id}/request?action=${action}`, body)).data
const fetchRequests   = async (status='pending'): Promise<ReviewRequest[]> =>
  (await http.get(`/review-requests?status=${status}`)).data
const approveRequest  = async (id: string, note='') => (await http.post(`/review-requests/${id}/approve`, { note })).data
const rejectRequest   = async (id: string, note='') => (await http.post(`/review-requests/${id}/reject`,  { note })).data

// ── Helpers ───────────────────────────────────────────────────────────────────

function agentColor(email: string) {
  const idx = email.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % AGENT_COLORS.length
  return AGENT_COLORS[idx]
}

function applyFilters(rows: Review[], f: Filters, userMap: Record<string,string> = {}): Review[] {
  return rows.filter(r => {
    if (f.status   && r.status   !== f.status)   return false
    if (f.plan     && r.app_plan !== f.plan)      return false
    if (f.star     && r.star     !== f.star)      return false
    if (f.pkg      && r.package  !== f.pkg)       return false
    if (f.app      && r.app      !== f.app)       return false
    if (f.dateFrom && r.review_date < f.dateFrom) return false
    if (f.dateTo   && r.review_date > f.dateTo)   return false
    if (f.agent) {
      const q = f.agent.toLowerCase()
      const match = [r.mentioned, r.cs1, r.cs2, r.tech].some(email => {
        if (!email) return false
        const displayName = userMap[email.toLowerCase()] || ''
        return email.toLowerCase().includes(q) || displayName.toLowerCase().includes(q)
      })
      if (!match) return false
    }
    return true
  })
}

// ── Cell renderers ────────────────────────────────────────────────────────────

function StatusCell({ value }: ICellRendererParams) {
  if (!value) return null
  const c = STATUS_COLOR[value] ?? '#888'
  return <Tag style={{ background:`${c}18`, color:c, border:`1px solid ${c}44`, fontWeight:600, fontSize:11, margin:0 }}>{value}</Tag>
}

function PlanCell({ value }: ICellRendererParams) {
  if (!value) return null
  return <Tag color={value === 'Paid' ? 'processing' : 'default'} style={{ margin:0, fontSize:10, fontWeight:600 }}>{value}</Tag>
}

function AgentCell(params: ICellRendererParams & { userMap?: Record<string,string> }) {
  const { value, userMap } = params
  if (!value) return <span style={{ color:'#94a3b8', fontSize:14 }}>—</span>
  const email       = value as string
  const displayName = userMap?.[email.toLowerCase()] || email.split('@')[0]
  const color       = agentColor(email)
  return (
    <Tooltip title={email}>
      <span style={{
        background: `${color}16`,
        color,
        borderRadius: 6,
        padding: '3px 10px',
        fontSize: 13,
        fontWeight: 600,
        cursor: 'default',
        border: `1px solid ${color}38`,
        display: 'inline-block',
        maxWidth: '100%',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        verticalAlign: 'middle',
        boxSizing: 'border-box',
      }}>
        {displayName}
      </span>
    </Tooltip>
  )
}

function PointCell({ value }: ICellRendererParams) {
  if (value == null) return null
  return <span style={{ fontWeight:700, color:'#6366f1' }}>{value}</span>
}

// ── Filter Bar ────────────────────────────────────────────────────────────────

const EMPTY: Filters = { status:'', plan:'', star:'', pkg:'', app:'', agent:'', dateFrom:'', dateTo:'', dateRange:null }

function ReviewFilterBar({ value, onChange, showAgent }: { value: Filters; onChange: (f:Filters)=>void; showAgent: boolean }) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch })

  const activeCount = [value.status, value.plan, value.star, value.pkg, value.app, value.agent, value.dateFrom].filter(Boolean).length

  return (
    <div style={{
      background:'#fff', borderRadius:10, boxShadow:'0 1px 4px #0001',
      padding:'10px 16px', marginBottom:10,
      display:'flex', flexWrap:'wrap', gap:'8px 20px', alignItems:'flex-end',
    }}>
      {/* Date */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>KHOẢNG NGÀY</Text>
        <RangePicker size="small" format="DD/MM/YYYY" value={value.dateRange}
          onChange={v => set({ dateRange: v as [Dayjs,Dayjs]|null, dateFrom: v?.[0]?.format('YYYY-MM-DD')||'', dateTo: v?.[1]?.format('YYYY-MM-DD')||'' })}
          style={{ width:210 }} allowClear placeholder={['Từ ngày','Đến ngày']} />
        <div style={{ marginTop:4, display:'flex', gap:4, flexWrap:'wrap' }}>
          {DATE_PRESETS.map(p => (
            <Tag key={p.label} style={{ cursor:'pointer', fontSize:11, padding:'0 6px', margin:0 }}
              color={value.dateFrom === p.range()[0].format('YYYY-MM-DD') ? 'blue' : undefined}
              onClick={() => { const r=p.range(); set({ dateRange:r, dateFrom:r[0].format('YYYY-MM-DD'), dateTo:r[1].format('YYYY-MM-DD') }) }}>
              {p.label}
            </Tag>
          ))}
        </div>
      </div>

      <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

      {/* Status */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>STATUS</Text>
        <Segmented size="small" value={value.status||'__all__'}
          onChange={v => set({ status: v==='__all__'?'':String(v) })}
          options={[{ label:'All', value:'__all__' }, ...STATUS_OPTIONS.map(s=>({ label:s, value:s }))]} />
      </div>

      <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

      {/* Plan */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>PLAN</Text>
        <Segmented size="small" value={value.plan||'__all__'}
          onChange={v => set({ plan: v==='__all__'?'':String(v) })}
          options={[{ label:'All', value:'__all__' }, { label:<span style={{color:'#475569',fontWeight:600}}>Free</span>, value:'Free' }, { label:<span style={{color:'#6366f1',fontWeight:600}}>Paid</span>, value:'Paid' }]} />
      </div>

      <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

      {/* Star */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>STAR</Text>
        <Select size="small" style={{ width:100 }} value={value.star||undefined}
          placeholder="All" allowClear onChange={v => set({ star:v??'' })}
          options={STAR_RATINGS.map(s=>({ label:`${'⭐'.repeat(Number(s))}`, value:s }))} />
      </div>

      <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

      {/* Package */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>PACKAGE</Text>
        <Select size="small" style={{ width:150 }} value={(value as Filters & { pkg?: string }).pkg||undefined}
          placeholder="All" allowClear onChange={v => set({ ...value, pkg: v??'' } as Filters)}
          options={PACKAGE_OPTIONS.map(s=>({ label:s, value:s }))} />
      </div>

      <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />

      {/* App */}
      <div>
        <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>APP</Text>
        <Segmented size="small" value={value.app||'__all__'}
          onChange={v => set({ app: v==='__all__'?'':String(v) })}
          options={[
            { label:'All', value:'__all__' },
            { label:<span style={{ color:APP_COLOR['SearchPie'], fontWeight:600 }}>SearchPie</span>, value:'SearchPie' },
            { label:<span style={{ color:APP_COLOR['DECO'], fontWeight:600 }}>DECO</span>, value:'DECO' },
          ]}
        />
      </div>

      {/* Agent — manager/admin only */}
      {showAgent && (
        <>
          <Divider type="vertical" style={{ height:44, margin:'0 4px' }} />
          <div>
            <Text style={{ fontSize:11, color:'#888', display:'block', marginBottom:4 }}>AGENT</Text>
            <Input size="small" style={{ width:180 }} value={value.agent}
              placeholder="Tìm tên hoặc email…" allowClear onChange={e => set({ agent:e.target.value })} />
          </div>
        </>
      )}

      {/* Reset */}
      <div style={{ marginLeft:'auto', display:'flex', gap:8, alignItems:'flex-end' }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={() => onChange(EMPTY)} style={{ color:'#888' }}>Reset</Button>
        {activeCount > 0 && (
          <Tag color="blue" style={{ margin:0 }}>{activeCount} filter{activeCount>1?'s':''} active</Tag>
        )}
      </div>
    </div>
  )
}

// ── Review Form ───────────────────────────────────────────────────────────────

function ReviewForm({
  form, users, isEdit = false, isManager = false,
}: {
  form: ReturnType<typeof Form.useForm>[0]
  users: UserInfo[]
  isEdit?: boolean
  isManager?: boolean
}) {
  const agentOptions = users.map(u => ({
    label: u.nickname?.trim() || u.name,
    value: u.email,
  }))

  return (
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'0 16px' }}>
      {/* Status — edit mode only, manager/admin only */}
      {isEdit && isManager && (
        <Form.Item name="status" label="Status" rules={[{ required:true }]}>
          <Select options={STATUS_OPTIONS.map(s=>({ label:s, value:s }))} />
        </Form.Item>
      )}
      <Form.Item name="app" label="App" rules={[{ required:true }]}>
        <Select
          options={APP_OPTIONS.map(a=>({ label:a, value:a }))}
          placeholder="Chọn app…"
        />
      </Form.Item>
      <Form.Item name="star" label="Star" rules={[{ required:true }]} initialValue="5">
        <Select
          options={STAR_RATINGS.map(s=>({ label: '⭐'.repeat(Number(s)) + ` (${s})`, value:s }))}
          placeholder="Chọn số sao…"
        />
      </Form.Item>
      <Form.Item name="package" label="Package">
        <Select
          options={PACKAGE_OPTIONS.map(s=>({ label:s, value:s }))}
          allowClear placeholder="Chọn package…"
        />
      </Form.Item>
      <Form.Item name="review_date" label="Review date" rules={[{ required:true }]}>
        <DatePicker format="DD/MM/YYYY" style={{ width:'100%' }} />
      </Form.Item>
      <Form.Item name="app_plan" label="App plan" initialValue="Free">
        <Select options={PLAN_OPTIONS.map(p=>({ label:p, value:p }))} />
      </Form.Item>
      <Form.Item name="customer_name" label="Customer" style={{ gridColumn:'span 2' }}>
        <Input />
      </Form.Item>
      <Form.Item name="link" label="Link Crisp" style={{ gridColumn:'span 2' }}>
        <Input placeholder="https://app.crisp.chat/..." />
      </Form.Item>
      <Form.Item name="mentioned" label="Mentioned">
        <Select options={agentOptions} allowClear showSearch
          optionFilterProp="label" placeholder="Chọn agent…" />
      </Form.Item>
      <Form.Item name="cs1" label="CS 1 (*)">
        <Select options={agentOptions} allowClear showSearch
          optionFilterProp="label" placeholder="Chọn agent…" />
      </Form.Item>
      <Form.Item name="cs2" label="CS 2">
        <Select options={agentOptions} allowClear showSearch
          optionFilterProp="label" placeholder="Chọn agent…" />
      </Form.Item>
      <Form.Item name="tech" label="Tech">
        <Select options={agentOptions} allowClear showSearch
          optionFilterProp="label" placeholder="Chọn agent…" />
      </Form.Item>
      <Form.Item name="notes" label="Notes" style={{ gridColumn:'span 2' }}>
        <Input.TextArea rows={2} />
      </Form.Item>
    </div>
  )
}

// ── Edit Score Modal ──────────────────────────────────────────────────────────

function EditScoreModal({
  rev, onClose, onSaved,
}: {
  rev: Review
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const qc = useQueryClient()

  const scoreMut = useMutation({
    mutationFn: (vals: Record<string,unknown>) =>
      updateScore(rev.id, { count: vals.count, point: vals.point, he_so: vals.he_so }),
    onSuccess: () => {
      message.success('Score updated')
      qc.invalidateQueries({ queryKey: ['reviews'] })
      qc.invalidateQueries({ queryKey: ['review-stats-own'] })
      onSaved()
    },
    onError: () => message.error('Failed to update score'),
  })

  return (
    <Modal
      title={`Edit Score — ${rev.customer_name || rev.id.slice(-6)}`}
      open onCancel={onClose}
      onOk={() => form.submit()} confirmLoading={scoreMut.isPending}
      okText="Save" width={400}
    >
      <Form form={form} layout="vertical" initialValues={{ count: rev.count, point: rev.point, he_so: rev.he_so }}
        onFinish={v => scoreMut.mutate(v as Record<string,unknown>)}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'0 16px' }}>
          <Form.Item name="count" label="Count" rules={[{ required:true }]}>
            <InputNumber min={0} style={{ width:'100%' }} />
          </Form.Item>
          <Form.Item name="point" label="Point" rules={[{ required:true }]}>
            <InputNumber min={0} step={0.5} style={{ width:'100%' }} />
          </Form.Item>
          <Form.Item name="he_so" label="Hệ số" rules={[{ required:true }]}>
            <InputNumber min={1} style={{ width:'100%' }} />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  )
}

// ── Pending Requests Panel ────────────────────────────────────────────────────

function RequestsPanel({ reviewSeqMap }: { reviewSeqMap: Record<string, number> }) {
  const qc = useQueryClient()
  const [noteMap, setNoteMap] = useState<Record<string,string>>({})
  const { data:requests=[], isLoading } = useQuery({ queryKey:['review-requests','pending'], queryFn:()=>fetchRequests('pending'), staleTime:15_000 })

  const approveMut = useMutation({
    mutationFn: ({ id }:{id:string}) => approveRequest(id, noteMap[id]||''),
    onSuccess: ()=>{ message.success('Approved'); qc.invalidateQueries({ queryKey:['review-requests'] }); qc.invalidateQueries({ queryKey:['reviews'] }) },
    onError: ()=>message.error('Failed'),
  })
  const rejectMut = useMutation({
    mutationFn: ({ id }:{id:string}) => rejectRequest(id, noteMap[id]||''),
    onSuccess: ()=>{ message.success('Rejected'); qc.invalidateQueries({ queryKey:['review-requests'] }) },
    onError: ()=>message.error('Failed'),
  })

  if (!isLoading && !requests.length)
    return <Text type="secondary" style={{ fontSize:13 }}>No pending requests.</Text>

  return (
    <div>
      {requests.map(req => (
        <div key={req.id} style={{ background:'#fff', border:'1px solid #e2e8f0', borderRadius:10, padding:'12px 16px', marginBottom:10 }}>
          <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8 }}>
            <Tag color={req.action==='delete'?'error':'processing'}>{req.action==='delete'?'Delete':'Update'}</Tag>
            <Text style={{ fontSize:12 }}>Review: <code style={{ background:'#f1f5f9', padding:'1px 6px', borderRadius:4 }}>
              {reviewSeqMap[req.review_id] != null ? `#${reviewSeqMap[req.review_id]}` : `#${req.review_id.slice(-4)}`}
            </code></Text>
            <Text type="secondary" style={{ fontSize:11 }}>by {req.requested_by}</Text>
            <Text type="secondary" style={{ fontSize:11, marginLeft:'auto' }}>{new Date(req.created_at).toLocaleDateString('vi-VN')}</Text>
          </div>
          {req.reason && <Text style={{ fontSize:12, display:'block', marginBottom:8, color:'#475569' }}>Lý do: {req.reason}</Text>}
          {req.action==='update' && Object.keys(req.changes).length>0 && (
            <div style={{ background:'#f8fafc', borderRadius:6, padding:'6px 10px', marginBottom:8, fontSize:12 }}>
              {Object.entries(req.changes).map(([k,v])=>(
                <div key={k}><strong>{k}</strong>: {String(v)}</div>
              ))}
            </div>
          )}
          <Space>
            <Input size="small" placeholder="Ghi chú (tuỳ chọn)" style={{ width:200 }}
              value={noteMap[req.id]||''} onChange={e=>setNoteMap(p=>({ ...p,[req.id]:e.target.value }))} />
            <Button size="small" type="primary" icon={<CheckOutlined />} loading={approveMut.isPending}
              onClick={()=>approveMut.mutate({ id:req.id })}>Approve</Button>
            <Button size="small" danger icon={<CloseOutlined />} loading={rejectMut.isPending}
              onClick={()=>rejectMut.mutate({ id:req.id })}>Reject</Button>
          </Space>
        </div>
      ))}
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function ReviewPerformance() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const gridRef = useRef<AgGridReact>(null)
  const [filters, setFilters]   = useState<Filters>(EMPTY)
  const [addOpen,   setAddOpen]   = useState(false)
  const [editRev,   setEditRev]   = useState<Review|null>(null)
  const [scoreRev,  setScoreRev]  = useState<Review|null>(null)
  const [reqRev,    setReqRev]    = useState<Review|null>(null)
  const [reqAction, setReqAction] = useState<'update'|'delete'>('update')
  const [addForm]  = Form.useForm()
  const [editForm] = Form.useForm()
  const [reqForm]  = Form.useForm()

  const isEditor = user?.role === 'admin' || user?.role === 'manager'

  const pendingCount = useQuery({
    queryKey: ['review-requests','pending'],
    queryFn: ()=>fetchRequests('pending'),
    enabled: isEditor, staleTime:15_000,
  }).data?.length ?? 0

  const { data:rawUsers=[] } = useQuery({
    queryKey: ['all-users'], queryFn: fetchAllUsers, staleTime: 10*60_000,
  })
  const userMap   = useMemo(() => buildUserMap(rawUsers), [rawUsers])
  const userOpts  = useMemo(() => rawUsers.map(u => ({
    label: u.nickname?.trim() || u.name,
    value: u.email,
  })), [rawUsers])

  const { data:rawReviews=[], isLoading, refetch, isFetching } = useQuery({
    queryKey: ['reviews'], queryFn: fetchReviews, staleTime:5*60_000,
  })

  const reviews = useMemo(() => applyFilters(rawReviews, filters, userMap), [rawReviews, filters, userMap])

  const reviewSeqMap = useMemo(() =>
    Object.fromEntries(rawReviews.filter(r => r.seq != null).map(r => [r.id, r.seq as number])),
  [rawReviews])

  // ── Mutations ────────────────────────────────────────────────────────────────

  const addMut = useMutation({
    mutationFn: (vals: Record<string,unknown>) => {
      const d = { ...vals, review_date: vals.review_date ? (vals.review_date as Dayjs).format('YYYY-MM-DD') : '' }
      return createReview(d)
    },
    onSuccess: ()=>{ message.success('Review added'); qc.invalidateQueries({ queryKey:['reviews'] }); setAddOpen(false); addForm.resetFields() },
    onError: ()=>message.error('Failed to add review'),
  })

  const editMut = useMutation({
    mutationFn: (vals: Record<string,unknown>) => {
      if (!editRev) return Promise.reject()
      const d = { ...vals, review_date: vals.review_date ? (vals.review_date as Dayjs).format('YYYY-MM-DD') : editRev.review_date }
      return updateReview(editRev.id, d)
    },
    onSuccess: ()=>{ message.success('Updated'); qc.invalidateQueries({ queryKey:['reviews'] }); setEditRev(null) },
    onError: ()=>message.error('Failed'),
  })

  const deleteMut = useMutation({
    mutationFn: deleteReview,
    onSuccess: ()=>{ message.success('Deleted'); qc.invalidateQueries({ queryKey:['reviews'] }) },
    onError: ()=>message.error('Failed'),
  })

  const reqMut = useMutation({
    mutationFn: ({ id, action, vals }:{ id:string; action:string; vals:Record<string,unknown> }) =>
      submitRequest(id, action, { reason: vals.reason as string, changes: vals.changes ?? {} }),
    onSuccess: ()=>{ message.success('Request sent — waiting for manager/admin approval'); setReqRev(null); reqForm.resetFields() },
    onError: ()=>message.error('Failed to send request'),
  })

  const openEdit = (rev: Review) => {
    setEditRev(rev)
    editForm.setFieldsValue({ ...rev, review_date: rev.review_date ? dayjs(rev.review_date) : null })
  }

  const openReq = (rev: Review, action: 'update'|'delete') => {
    setReqRev(rev); setReqAction(action)
    if (action==='update') reqForm.setFieldsValue({ ...rev, review_date: rev.review_date ? dayjs(rev.review_date) : null })
  }

  // ── Columns ──────────────────────────────────────────────────────────────────

  const ActionsCell = useCallback(({ data:rev }:ICellRendererParams<Review>) => {
    if (!rev) return null
    return (
      <Space size={2} style={{ height:'100%', alignItems:'center' }}>
        {isEditor ? (
          <>
            <Tooltip title="Edit">
              <Button size="small" type="text" icon={<EditOutlined />} onClick={()=>openEdit(rev)} />
            </Tooltip>
            <Tooltip title="Edit Score">
              <Button size="small" type="text" icon={<FilterOutlined />} onClick={()=>setScoreRev(rev)} />
            </Tooltip>
            <Tooltip title="Delete">
              <Button size="small" type="text" danger icon={<DeleteOutlined />}
                onClick={()=>Modal.confirm({ title:'Delete this review?', okType:'danger', okText:'Delete', onOk:()=>deleteMut.mutate(rev.id) })} />
            </Tooltip>
          </>
        ) : (
          <>
            <Tooltip title="Đề xuất chỉnh sửa">
              <Button size="small" type="text" icon={<EditOutlined />} onClick={()=>openReq(rev,'update')} />
            </Tooltip>
            <Tooltip title="Yêu cầu xóa">
              <Button size="small" type="text" danger icon={<SendOutlined />} onClick={()=>openReq(rev,'delete')} />
            </Tooltip>
          </>
        )}
      </Space>
    )
  }, [isEditor, deleteMut])

  const columnDefs = useMemo<ColDef[]>(()=>[
    { field:'seq', headerName:'#', width:52, pinned:'left',
      cellRenderer:({ value }:ICellRendererParams) =>
        value != null
          ? <span style={{ fontWeight:600, fontSize:12, color:'#64748b' }}>{value}</span>
          : null,
    },
    { field:'status',        headerName:'Status',    width:92,  pinned:'left', cellRenderer:StatusCell },
    { field:'app',           headerName:'App',       width:100,
      cellRenderer:({ value }:ICellRendererParams) => {
        if (!value) return null
        const c = APP_COLOR[value] ?? '#888'
        return <Tag style={{ background:`${c}18`, color:c, border:`1px solid ${c}44`, fontWeight:600, fontSize:11, margin:0 }}>{value}</Tag>
      }
    },
    { field:'star', headerName:'Star', width:72,
      cellRenderer:({ value }:ICellRendererParams) => value
        ? <span style={{ fontWeight:700, fontSize:13 }}>⭐ <span style={{ color:'#0f172a' }}>{value}</span></span>
        : null },
    { field:'package',       headerName:'Package',   width:140 },
    { field:'review_date',   headerName:'Date',      width:105, sort:'desc' },
    { field:'customer_name', headerName:'Customer',  width:175 },
    { field:'link',          headerName:'Link',      width:80,
      cellRenderer:({ value }:ICellRendererParams)=>
        value ? <a href={value} target="_blank" rel="noreferrer" style={{ fontSize:11, color:'#6366f1' }}>↗ Crisp</a> : null
    },
    { field:'app_plan',  headerName:'Plan',     width:76,  cellRenderer:PlanCell },
    { field:'mentioned', headerName:'Mentioned', width:165, cellRenderer:AgentCell, cellRendererParams:{ userMap } },
    { field:'cs1',       headerName:'CS 1 (*)',  width:165, cellRenderer:AgentCell, cellRendererParams:{ userMap } },
    { field:'cs2',       headerName:'CS 2',      width:165, cellRenderer:AgentCell, cellRendererParams:{ userMap } },
    { field:'tech',      headerName:'Tech',      width:165, cellRenderer:AgentCell, cellRendererParams:{ userMap } },
    { field:'point',     headerName:'Point',     width:80,  type:'numericColumn', cellRenderer:PointCell },
    { field:'notes',     headerName:'Notes',     width:230, tooltipField:'notes' },
    { headerName:'', cellRenderer:ActionsCell, width:isEditor ? 110 : 78, pinned:'right',
      sortable:false, resizable:false, suppressMovable:true },
  ], [ActionsCell, userMap])

  // ── Own stats (support) ──────────────────────────────────────────────────────

  const { data: ownStats } = useQuery({
    queryKey: ['review-stats-own', user?.email],
    queryFn: async () => {
      const res = await http.get('/review-stats')
      const list = res.data as { email: string; total_count: number; total_point: number; by_role: Record<string,number> }[]
      // Support: backend trả về 1 item (của mình)
      // Admin/Manager: tìm trong list theo email
      return list.find(r => r.email === user?.email?.toLowerCase()) ?? list[0]
    },
    enabled: !!user,
    staleTime: 60_000,
  })

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* Support: personal stats bar */}
      {ownStats && (
        <div style={{
          background: '#fff', borderRadius: 10,
          boxShadow: '0 1px 4px #0001', border: '1px solid #e2e8f0',
          padding: '12px 20px', marginBottom: 10,
          display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap',
        }}>
          <Text strong style={{ fontSize: 13, color: '#0f172a' }}>Thống kê của bạn</Text>
          <div style={{ width: 1, height: 28, background: '#e2e8f0' }} />
          {[
            { label: 'Tổng reviews', value: ownStats.total_count, color: '#0f172a' },
            { label: 'Tổng điểm',   value: ownStats.total_point.toFixed(1), color: '#6366f1' },
          ].map(item => (
            <div key={item.label} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
              <span style={{ color: item.color, fontWeight: 800, fontSize: 20, letterSpacing: -0.5 }}>{item.value}</span>
            </div>
          ))}
          <div style={{ width: 1, height: 28, background: '#e2e8f0' }} />
          {[
            { key: 'mentioned', label: 'Mentioned', color: '#6366f1' },
            { key: 'cs1',      label: 'CS 1',      color: '#0891b2' },
            { key: 'cs2',      label: 'CS 2',      color: '#16a34a' },
            { key: 'tech',     label: 'Tech',      color: '#f59e0b' },
          ].map(role => (
            <div key={role.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 11, fontWeight: 700,
                background: `${role.color}15`, color: role.color,
                border: `1px solid ${role.color}33`,
                borderRadius: 99, padding: '1px 8px',
              }}>{role.label}</span>
              <span style={{ fontWeight: 700, fontSize: 15, color: '#0f172a' }}>
                {ownStats.by_role?.[role.key] ?? 0}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Filter bar */}
      <ReviewFilterBar value={filters} onChange={setFilters} showAgent={isEditor} />

      {/* Toolbar */}
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:8 }}>
        <Text type="secondary" style={{ fontSize:13 }}>
          {isFetching ? 'Loading…' : `${reviews.length}${rawReviews.length!==reviews.length ? `/${rawReviews.length}` : ''} records`}
        </Text>
        <Button size="small" onClick={()=>refetch()} loading={isFetching}>Refresh</Button>
        <div style={{ marginLeft:'auto' }}>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={()=>setAddOpen(true)}>
            Add review
          </Button>
        </div>
      </div>

      {/* Tabs: table + requests (manager/admin) */}
      <Tabs size="small" tabBarStyle={{ marginBottom:8 }} items={[
        {
          key:'table',
          label:'Reviews',
          children:(
            <div className="review-grid" style={{ height:'calc(100vh - 260px)', minHeight:400 }}>
              <AgGridReact<Review>
                ref={gridRef}
                rowData={reviews}
                columnDefs={columnDefs}
                defaultColDef={{ resizable:true, sortable:true, cellStyle:{ fontSize:13 }, cellDataType:false }}
                getRowId={(p:GetRowIdParams<Review>)=>p.data.id}
                loading={isLoading}
                pagination paginationPageSize={50}
                paginationPageSizeSelector={[25,50,100]}
                rowHeight={32} headerHeight={34}
                tooltipShowDelay={400}
                enableCellTextSelection
              />
            </div>
          ),
        },
        ...(isEditor ? [{
          key:'requests',
          label:(
            <Badge count={pendingCount} size="small">
              <span style={{ paddingRight: pendingCount ? 8 : 0 }}>Pending requests</span>
            </Badge>
          ),
          children:<RequestsPanel reviewSeqMap={reviewSeqMap} />,
        }] : []),
      ]} />

      {/* Add Review Modal */}
      <Modal title="Add Review" open={addOpen}
        onCancel={()=>{ setAddOpen(false); addForm.resetFields() }}
        onOk={()=>addForm.submit()} confirmLoading={addMut.isPending} okText="Add" width={640}>
        <Form form={addForm} layout="vertical" onFinish={v=>addMut.mutate(v as Record<string,unknown>)}>
          <ReviewForm form={addForm} users={rawUsers} isEdit={false} isManager={isEditor} />
        </Form>
      </Modal>

      {/* Edit Review Modal */}
      {editRev && (
        <Modal title={`Edit — ${editRev.customer_name||editRev.id}`} open
          onCancel={()=>setEditRev(null)} onOk={()=>editForm.submit()}
          confirmLoading={editMut.isPending} okText="Save" width={640}>
          <Form form={editForm} layout="vertical" onFinish={v=>editMut.mutate(v as Record<string,unknown>)}>
            <ReviewForm form={editForm} users={rawUsers} isEdit isManager={isEditor} />
          </Form>
        </Modal>
      )}

      {/* Edit Score Modal — admin/manager only */}
      {scoreRev && isEditor && (
        <EditScoreModal rev={scoreRev} onClose={()=>setScoreRev(null)} onSaved={()=>setScoreRev(null)} />
      )}

      {/* Request Change Modal */}
      {reqRev && (
        <Modal
          title={reqAction==='delete' ? `Yêu cầu xóa — ${reqRev.customer_name}` : `Đề xuất chỉnh sửa — ${reqRev.customer_name}`}
          open onCancel={()=>{ setReqRev(null); reqForm.resetFields() }}
          onOk={()=>reqForm.submit()} confirmLoading={reqMut.isPending} okText="Gửi yêu cầu" width={640}>
          <Form form={reqForm} layout="vertical" onFinish={vals=>{
            const changes = reqAction==='update'
              ? { ...vals, review_date: (vals.review_date as Dayjs)?.format?.('YYYY-MM-DD') ?? vals.review_date, reason:undefined }
              : {}
            reqMut.mutate({ id:reqRev.id, action:reqAction, vals:{ reason:vals.reason??'', changes } })
          }}>
            <Form.Item name="reason" label="Lý do" rules={[{ required:true }]}>
              <Input.TextArea rows={2} placeholder="Vì sao bạn muốn thay đổi/xóa review này?" />
            </Form.Item>
            {reqAction==='update' && <ReviewForm form={reqForm} users={rawUsers} isEdit={false} isManager={false} />}
          </Form>
        </Modal>
      )}
    </div>
  )
}
