import { useCallback, useMemo, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
  type ColGroupDef,
  type ICellRendererParams,
  type ITooltipParams,
  type GetRowIdParams,
  type RowSelectionOptions,
  type GridReadyEvent,
} from 'ag-grid-community'
import {
  Button,
  message,
  Modal,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  EyeOutlined,
  FormOutlined,
  SyncOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { deleteRecord, fetchRecords, resolveRecord } from '../api'
import { invalidateAll } from '../cache'
import { useAuth } from '../context/AuthContext'
import type { Filters, QARecord } from '../types'
import { CRITERIA_KEYS, CRITERIA_LABELS, CRITERIA_MAX } from '../types'
import EditModal from './EditModal'
import RegradeModal from './RegradeModal'
import DetailModal from './DetailModal'
import ScoreEditModal from './ScoreEditModal'

ModuleRegistry.registerModules([AllCommunityModule])

// ── Custom tooltip ────────────────────────────────────────────────────────────

function CriteriaTooltip({ value }: ITooltipParams) {
  if (!value) return null
  return (
    <div style={{
      background: '#1e293b',
      color: '#e2e8f0',
      padding: '10px 14px',
      borderRadius: 8,
      maxWidth: 300,
      fontSize: 12,
      lineHeight: 1.65,
      boxShadow: '0 6px 20px #00000055',
      border: '1px solid #334155',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      pointerEvents: 'none',
    }}>
      {String(value)}
    </div>
  )
}

// ── Colour helpers ────────────────────────────────────────────────────────────

function scoreColor(score: number) {
  if (score >= 9) return '#52c41a'
  if (score >= 7.5) return '#1677ff'
  if (score >= 5) return '#faad14'
  return '#ff4d4f'
}

function criteriaRatio(score: number, max: number) {
  return max > 0 ? score / max : 1
}

// ── Cell renderers ────────────────────────────────────────────────────────────

function ScoreCell({ value }: ICellRendererParams) {
  if (value == null) return <span style={{ color: '#bbb' }}>—</span>
  const color = scoreColor(value)
  return (
    <span
      style={{
        fontWeight: 700,
        fontSize: 14,
        color,
        background: `${color}18`,
        borderRadius: 4,
        padding: '1px 7px',
        display: 'inline-block',
      }}
    >
      {(value as number).toFixed(2)}
    </span>
  )
}

function AppCell({ value }: ICellRendererParams) {
  return (
    <Tag color={value === 'DECO' ? 'purple' : 'cyan'} style={{ margin: 0, fontSize: 11 }}>
      {value}
    </Tag>
  )
}

function ResolvedCell({ value }: ICellRendererParams) {
  return value ? (
    <Tag color="success" style={{ margin: 0, fontSize: 11 }}>
      ✓ Resolved
    </Tag>
  ) : (
    <Tag style={{ margin: 0, fontSize: 11 }}>Open</Tag>
  )
}

function TagsCell({ value }: ICellRendererParams) {
  const tags = (value as string[]) || []
  if (!tags.length) return null
  return (
    <span style={{ display: 'flex', flexWrap: 'wrap', gap: 2, lineHeight: '18px' }}>
      {tags.slice(0, 3).map((t, i) => (
        <Tag key={i} style={{ fontSize: 11, padding: '0 4px', margin: 0, lineHeight: '16px' }}>
          {t}
        </Tag>
      ))}
      {tags.length > 3 && (
        <Tag style={{ fontSize: 11, padding: '0 4px', margin: 0 }}>+{tags.length - 3}</Tag>
      )}
    </span>
  )
}

function CriteriaCell(params: ICellRendererParams & { criteriaKey?: string }) {
  const { value } = params
  const key = params.criteriaKey
  if (value == null || !key) return <span style={{ color: '#bbb' }}>—</span>
  const max = CRITERIA_MAX[key as keyof typeof CRITERIA_MAX]
  const ratio = criteriaRatio(value as number, max)
  const color = ratio >= 1 ? '#52c41a' : ratio >= 0.7 ? '#faad14' : '#ff4d4f'
  const deducted = (value as number) < max
  return (
    <span
      style={{
        color,
        fontWeight: deducted ? 600 : 400,
        fontSize: 12,
      }}
    >
      {(value as number)}
      <span style={{ color: '#999', fontSize: 10 }}>/{max}</span>
    </span>
  )
}

// ── AgentCell ─────────────────────────────────────────────────────────────────

interface UserInfo { email: string; name: string; nickname: string; picture: string; role: string; crisp_nickname?: string }

const http = axios.create({ baseURL: '/api', withCredentials: true })

function AgentCell({ value, agentMap }: { value: string; agentMap: Record<string, UserInfo> }) {
  const user = value ? agentMap[value] : undefined
  if (!user) {
    return <span style={{ fontSize: 13, color: '#374151' }}>{value || '—'}</span>
  }
  const displayName = user.nickname?.trim() || user.name
  return (
    <Tooltip
      title={
        <div style={{ padding: '4px 0' }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{displayName}</div>
          {user.nickname?.trim() && user.nickname !== user.name && (
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{user.name}</div>
          )}
          <div style={{ fontSize: 11, color: '#94a3b8' }}>{user.email}</div>
          <div style={{ marginTop: 4 }}>
            <span style={{
              fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 99,
              background: user.role === 'admin' ? '#6366f122' : user.role === 'manager' ? '#0891b222' : '#16a34a22',
              color: user.role === 'admin' ? '#6366f1' : user.role === 'manager' ? '#0891b2' : '#16a34a',
            }}>
              {user.role}
            </span>
          </div>
        </div>
      }
      placement="right"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'default' }}>
        {user.picture
          ? <img src={user.picture} alt="" style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0 }} />
          : <div style={{ width: 22, height: 22, borderRadius: '50%', background: '#e2e8f0', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#64748b' }}>{displayName[0]?.toUpperCase()}</div>
        }
        <span style={{ fontSize: 13, fontWeight: 500, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{displayName}</span>
      </div>
    </Tooltip>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  filters: Filters
}

export default function QATable({ filters }: Props) {
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'manager'
  const gridRef = useRef<AgGridReact>(null)
  const queryClient = useQueryClient()

  const [editRecord, setEditRecord] = useState<QARecord | null>(null)
  const [regradeRec, setRegradeRec] = useState<QARecord | null>(null)
  const [detailRec, setDetailRec] = useState<QARecord | null>(null)
  const [scoreEditRec, setScoreEditRec] = useState<QARecord | null>(null)

  // ── Build API params ──────────────────────────────────────────────────────

  const params = useMemo(() => {
    const p: Record<string, unknown> = {
      page_size: filters.chat_link ? 10 : 10000,
      sort_by: 'date',
      sort_dir: -1,
    }
    if (filters.app) p.app = filters.app
    if (filters.agent) p.agent = filters.agent
    if (filters.date_from) p.date_from = filters.date_from
    if (filters.date_to) p.date_to = filters.date_to
    if (filters.score_min > 0) p.score_min = filters.score_min
    if (filters.score_max < 10) p.score_max = filters.score_max
    if (filters.is_resolved === 'true') p.is_resolved = true
    if (filters.is_resolved === 'false') p.is_resolved = false
    if (filters.chat_link) p.chat_link = filters.chat_link
    return p
  }, [filters])

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['records', params],
    queryFn: () => fetchRecords(params as Parameters<typeof fetchRecords>[0]),
    staleTime: 15_000,
  })

  const { data: agentMap = {} } = useQuery<Record<string, UserInfo>>({
    queryKey: ['agent-map'],
    queryFn: () => http.get('/users/agent-map').then(r => r.data),
    staleTime: 5 * 60_000,
  })

  // ── Mutations ─────────────────────────────────────────────────────────────

  const deleteMut = useMutation({
    mutationFn: deleteRecord,
    onSuccess: () => {
      message.success('Record deleted')
      invalidateAll(queryClient)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Delete failed')
    },
  })

  const resolveMut = useMutation({
    mutationFn: resolveRecord,
    onSuccess: () => {
      message.success('Chat resolved in Crisp ✓')
      invalidateAll(queryClient)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Resolve failed')
    },
  })

  // ── Action handlers ───────────────────────────────────────────────────────

  const handleDelete = useCallback(
    (rec: QARecord) => {
      Modal.confirm({
        title: 'Delete this record?',
        content: `${rec.primary_operator} · ${rec.date} · ${rec.app}`,
        okType: 'danger',
        okText: 'Delete',
        onOk: () => deleteMut.mutate(rec.id),
      })
    },
    [deleteMut],
  )

  const handleResolve = useCallback(
    (rec: QARecord) => {
      Modal.confirm({
        title: 'Resolve in Crisp?',
        icon: <WarningOutlined style={{ color: '#faad14' }} />,
        content: (
          <>
            <Typography.Paragraph>
              Resolving <strong>{rec.session_id}</strong> via the Crisp API will mark the
              conversation as resolved. This action cannot be undone.
            </Typography.Paragraph>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Agent: {rec.primary_operator} · {rec.date}
            </Typography.Text>
          </>
        ),
        okText: 'Resolve',
        onOk: () => resolveMut.mutate(rec.id),
      })
    },
    [resolveMut],
  )

  // ── Actions cell renderer ─────────────────────────────────────────────────

  const ActionsCell = useCallback(
    ({ data: rec }: ICellRendererParams<QARecord>) => {
      if (!rec) return null
      return (
        <Space size={2} style={{ height: '100%', alignItems: 'center' }}>
          {/* View detail — all roles */}
          <Tooltip title="Xem chi tiết">
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => setDetailRec(rec)} />
          </Tooltip>

          {/* Edit actions — manager/admin only */}
          {canEdit && (
            <>
              <Tooltip title="Sửa thông tin">
                <Button size="small" type="text" icon={<EditOutlined />} onClick={() => setEditRecord(rec)} />
              </Tooltip>
              <Tooltip title="Sửa điểm từng tiêu chí">
                <Button size="small" type="text" icon={<FormOutlined style={{ color: '#1677ff' }} />} onClick={() => setScoreEditRec(rec)} />
              </Tooltip>
              <Tooltip title="Chấm lại bằng AI">
                <Button size="small" type="text" icon={<SyncOutlined />} onClick={() => setRegradeRec(rec)} />
              </Tooltip>
            </>
          )}
          {canEdit && !rec.is_resolved && (
            <Tooltip title="Resolve in Crisp">
              <Button
                size="small"
                type="text"
                icon={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                onClick={() => handleResolve(rec)}
                loading={resolveMut.isPending && resolveMut.variables === rec.id}
              />
            </Tooltip>
          )}
          {rec.crisp_url && (
            <Tooltip title="Open Crisp URL">
              <Button size="small" type="text" icon={<ExportOutlined />} onClick={() => window.open(rec.crisp_url!, '_blank')} />
            </Tooltip>
          )}
          {canEdit && (
          <Tooltip title="Delete">
            <Button
              size="small" type="text" danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(rec)}
            />
          </Tooltip>
          )}
        </Space>
      )
    },
    [handleDelete, handleResolve, resolveMut.isPending, resolveMut.variables, canEdit],
  )

  // ── Column definitions ────────────────────────────────────────────────────

  const columnDefs = useMemo<(ColDef | ColGroupDef)[]>(
    () => [
      // Pinned left
      {
        checkboxSelection: true,
        headerCheckboxSelection: true,
        width: 44,
        minWidth: 44,
        maxWidth: 44,
        pinned: 'left' as const,
        resizable: false,
        suppressMovable: true,
        sortable: false,
        lockPinned: true,
      },
      {
        field: 'date',
        headerName: 'Date',
        width: 108,
        minWidth: 90,
        pinned: 'left' as const,
        sortable: true,
        sort: 'desc',
      },
      {
        field: 'app',
        headerName: 'App',
        width: 98,
        minWidth: 80,
        pinned: 'left' as const,
        cellRenderer: AppCell,
        sortable: true,
      },
      {
        field: 'primary_operator',
        headerName: 'Agent',
        width: 165,
        minWidth: 120,
        pinned: 'left' as const,
        sortable: true,
        cellRenderer: (params: ICellRendererParams) => (
          <AgentCell value={params.value} agentMap={agentMap} />
        ),
      },

      // Basic info
      {
        field: 'customer',
        headerName: 'Customer',
        width: 155,
        sortable: true,
      },
      {
        headerName: 'Score /10',
        valueGetter: (p) => p.data?.grading?.final_score_10,
        cellRenderer: ScoreCell,
        width: 100,
        minWidth: 90,
        sortable: true,
        sort: 'desc',
        comparator: (a: number, b: number) => (a ?? 0) - (b ?? 0),
      },
      {
        field: 'is_resolved',
        headerName: 'Status',
        width: 105,
        cellRenderer: ResolvedCell,
        sortable: true,
      },
      // Tags — hidden by default, visible via Detail modal
      {
        field: 'tags',
        headerName: 'Tags',
        width: 220,
        cellRenderer: TagsCell,
        sortable: false,
        hide: true,
      },

      // Criteria column group — OPEN by default, shows all 14 criteria
      {
        headerName: 'Criteria (20pt)',
        openByDefault: true,
        children: [
          // Shown only when group is CLOSED (compact summary)
          {
            headerName: 'Total /20',
            valueGetter: (p: { data?: QARecord }) => p.data?.grading?.total_score_20,
            width: 90,
            sortable: true,
            columnGroupShow: 'closed' as const,
            cellStyle: { fontWeight: 600 },
          },
          // Individual criteria shown when group is OPEN (default)
          ...CRITERIA_KEYS.map((key) => ({
            headerName: CRITERIA_LABELS[key],
            headerTooltip: `${CRITERIA_LABELS[key]} — max: ${CRITERIA_MAX[key]}`,
            valueGetter: (p: { data?: QARecord }) => p.data?.grading?.criteria?.[key]?.score,
            tooltipValueGetter: (p: { data?: QARecord }) =>
              p.data?.grading?.criteria?.[key]?.justification,
            tooltipComponent: CriteriaTooltip,
            cellRenderer: CriteriaCell,
            cellRendererParams: { criteriaKey: key },
            width: 82,
            minWidth: 68,
            sortable: true,
            columnGroupShow: 'open' as const,
            comparator: (a: number, b: number) => (a ?? 0) - (b ?? 0),
          })),
        ],
      },

      // Summary — hidden by default, visible via Detail modal
      {
        field: 'summary',
        headerName: 'Summary',
        width: 320,
        cellStyle: { fontSize: 12, color: '#555', lineHeight: '18px' },
        sortable: false,
        hide: true,
        wrapText: false,
      },

      // Actions (pinned right)
      {
        headerName: 'Actions',
        cellRenderer: ActionsCell,
        width: 210,
        minWidth: 190,
        pinned: 'right' as const,
        sortable: false,
        resizable: false,
        suppressMovable: true,
        lockPinned: true,
      },
    ],
    [ActionsCell],
  )

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
      suppressMovable: false,
    }),
    [],
  )

  const rowSelection = useMemo<RowSelectionOptions>(
    () => ({ mode: 'multiRow', checkboxes: true, headerCheckbox: true }),
    [],
  )

  const getRowId = useCallback((p: GetRowIdParams<QARecord>) => p.data.id, [])

  const onGridReady = useCallback((e: GridReadyEvent) => {
    e.api.sizeColumnsToFit()
  }, [])

  // ── Toolbar: bulk resolve ─────────────────────────────────────────────────

  const handleBulkResolve = () => {
    const selected = gridRef.current?.api.getSelectedRows() as QARecord[]
    const unresolved = selected?.filter((r) => !r.is_resolved) || []
    if (!unresolved.length) {
      message.info('No unresolved rows selected')
      return
    }
    Modal.confirm({
      title: `Resolve ${unresolved.length} chats in Crisp?`,
      icon: <WarningOutlined style={{ color: '#faad14' }} />,
      content: `This will mark ${unresolved.length} conversation(s) as resolved in Crisp. Cannot be undone.`,
      okText: `Resolve ${unresolved.length}`,
      onOk: async () => {
        for (const rec of unresolved) {
          await resolveRecord(rec.id).catch((e) => {
            const err = e as { response?: { data?: { detail?: string } } }
            message.error(`${rec.session_id}: ${err.response?.data?.detail || 'failed'}`)
          })
        }
        message.success(`Resolved ${unresolved.length} chats`)
        invalidateAll(queryClient)
      },
    })
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div>
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {isFetching
            ? 'Loading…'
            : `${data?.total ?? 0} total · showing ${data?.records?.length ?? 0}`}
        </Typography.Text>

        {/* Last fetched time from cached_at field */}
        {data?.cached_at && !isFetching && (
          <Typography.Text type="secondary" style={{ fontSize: 11, color: '#94a3b8' }}>
            · cached {(() => {
              const s = Math.round((Date.now() - new Date(data.cached_at as string).getTime()) / 1000)
              if (s < 60) return `${s}s ago`
              return `${Math.round(s / 60)}m ago`
            })()}
          </Typography.Text>
        )}

        <Button size="small" onClick={() => refetch()} loading={isFetching}>
          Refresh
        </Button>

        {/* Clear server cache + refetch */}
        <Button
          size="small"
          style={{ color: '#6366f1', borderColor: '#e0e7ff' }}
          onClick={async () => {
            await invalidateAll(queryClient)
            message.success('Cache cleared')
          }}
        >
          Clear cache
        </Button>

        <Button
          size="small"
          icon={<CheckCircleOutlined />}
          onClick={handleBulkResolve}
        >
          Bulk resolve selected
        </Button>
      </div>

      {/* AG-Grid */}
      <div
        className="ag-theme-quartz"
        style={{ height: 'calc(100vh - 210px)', minHeight: 400 }}
      >
        <AgGridReact<QARecord>
          ref={gridRef}
          rowData={data?.records ?? []}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection={rowSelection}
          getRowId={getRowId}
          onGridReady={onGridReady}
          pagination
          paginationPageSize={50}
          paginationPageSizeSelector={[25, 50, 100, 200]}
          loading={isLoading}
          tooltipShowDelay={400}
          enableCellTextSelection
          suppressCellFocus={false}
          rowHeight={36}
          headerHeight={38}
          groupHeaderHeight={34}
          suppressAnimationFrame={false}
        />
      </div>

      {/* Modals */}
      {editRecord && (
        <EditModal
          record={editRecord}
          onClose={() => setEditRecord(null)}
          onSuccess={(updated) => {
            setEditRecord(null)
            gridRef.current?.api.applyTransaction({ update: [updated] })
            invalidateAll(queryClient)
          }}
        />
      )}

      {regradeRec && (
        <RegradeModal
          record={regradeRec}
          onClose={() => setRegradeRec(null)}
          onSuccess={(updated) => {
            setRegradeRec(null)
            gridRef.current?.api.applyTransaction({ update: [updated] })
            invalidateAll(queryClient)
          }}
        />
      )}

      {detailRec && <DetailModal record={detailRec} onClose={() => setDetailRec(null)} />}

      {scoreEditRec && (
        <ScoreEditModal
          record={scoreEditRec}
          onClose={() => setScoreEditRec(null)}
          onSuccess={(updated) => {
            setScoreEditRec(null)
            gridRef.current?.api.applyTransaction({ update: [updated] })
            invalidateAll(queryClient)
          }}
        />
      )}
    </div>
  )
}
