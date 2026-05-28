import { useState } from 'react'
import {
  Card,
  DatePicker,
  Form,
  Select,
  Button,
  Table,
  Tag,
  Typography,
  Space,
  Statistic,
  Row,
  Col,
  Progress,
} from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { fetchStats } from '../api'
import type { Stats } from '../types'

const { RangePicker } = DatePicker
const { Text, Title } = Typography

interface AgentRow {
  agent: string
  count: number
  avg_score: number | null
}

function scoreColor(score: number | null) {
  if (score == null) return '#bbb'
  if (score >= 9) return '#52c41a'
  if (score >= 7.5) return '#1677ff'
  if (score >= 5) return '#faad14'
  return '#ff4d4f'
}

function ScoreTag({ score }: { score: number | null }) {
  if (score == null) return <span style={{ color: '#bbb' }}>—</span>
  const color = scoreColor(score)
  return (
    <span
      style={{
        fontWeight: 700,
        fontSize: 14,
        color,
        background: `${color}18`,
        borderRadius: 4,
        padding: '1px 8px',
      }}
    >
      {score.toFixed(2)}
    </span>
  )
}

export default function AgentStatsTab() {
  const [form] = Form.useForm()
  const [queryParams, setQueryParams] = useState<{
    app: string
    date_from: string
    date_to: string
  }>({ app: '', date_from: '', date_to: '' })

  const { data, isLoading } = useQuery<Stats>({
    queryKey: ['stats', queryParams.app, queryParams.date_from, queryParams.date_to],
    queryFn: () =>
      fetchStats({
        app: queryParams.app || undefined,
        date_from: queryParams.date_from || undefined,
        date_to: queryParams.date_to || undefined,
      }),
    staleTime: 30_000,
  })

  const handleFilter = (values: Record<string, unknown>) => {
    const range = values.dateRange as [dayjs.Dayjs, dayjs.Dayjs] | null
    setQueryParams({
      app: (values.app as string) || '',
      date_from: range?.[0]?.format('YYYY-MM-DD') || '',
      date_to: range?.[1]?.format('YYYY-MM-DD') || '',
    })
  }

  // Build sorted agent rows
  const agentRows: AgentRow[] = Object.entries(data?.by_agent || {})
    .map(([agent, v]) => ({ agent, count: v.count, avg_score: v.avg_score }))
    .sort((a, b) => (b.avg_score ?? 0) - (a.avg_score ?? 0))

  const maxScore = Math.max(...agentRows.map((r) => r.avg_score ?? 0), 1)

  const columns = [
    {
      title: '#',
      key: 'rank',
      width: 48,
      render: (_: unknown, __: AgentRow, idx: number) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {idx + 1}
        </Text>
      ),
    },
    {
      title: 'Agent',
      dataIndex: 'agent',
      key: 'agent',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: 'Chats',
      dataIndex: 'count',
      key: 'count',
      width: 80,
      sorter: (a: AgentRow, b: AgentRow) => a.count - b.count,
      render: (v: number) => <Tag>{v}</Tag>,
    },
    {
      title: 'Avg Score /10',
      dataIndex: 'avg_score',
      key: 'avg_score',
      width: 200,
      defaultSortOrder: 'descend' as const,
      sorter: (a: AgentRow, b: AgentRow) => (a.avg_score ?? 0) - (b.avg_score ?? 0),
      render: (score: number | null, row: AgentRow) => (
        <Space size={8} style={{ width: '100%' }}>
          <ScoreTag score={score} />
          <Progress
            percent={score != null ? Math.round((score / 10) * 100) : 0}
            showInfo={false}
            strokeColor={scoreColor(score)}
            trailColor="#f0f0f0"
            style={{ width: 120, marginBottom: 0 }}
            size="small"
          />
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* Filter */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" onFinish={handleFilter}>
          <Form.Item name="dateRange" label="Date range">
            <RangePicker size="small" format="YYYY-MM-DD" style={{ width: 240 }} allowClear />
          </Form.Item>
          <Form.Item name="app" label="App">
            <Select
              size="small"
              style={{ width: 120 }}
              placeholder="All apps"
              allowClear
              options={[
                { label: 'DECO', value: 'DECO' },
                { label: 'SearchPie', value: 'SearchPie' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" size="small" icon={<SearchOutlined />}>
              Load
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* Overview stats */}
      {data && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          {[
            { title: 'Total chats', value: data.total },
            {
              title: 'Avg score',
              value: data.avg_score ?? '—',
              suffix: data.avg_score != null ? '/10' : '',
              precision: 2,
              valueStyle: { color: scoreColor(data.avg_score) },
            },
            {
              title: 'Min score',
              value: data.min_score ?? '—',
              suffix: data.min_score != null ? '/10' : '',
              precision: 2,
              valueStyle: { color: scoreColor(data.min_score) },
            },
            {
              title: 'Max score',
              value: data.max_score ?? '—',
              suffix: data.max_score != null ? '/10' : '',
              precision: 2,
              valueStyle: { color: scoreColor(data.max_score) },
            },
            ...Object.entries(data.by_app).map(([app, count]) => ({
              title: app,
              value: count,
              suffix: 'chats',
            })),
          ].map((s, i) => (
            <Col key={i} xs={12} sm={8} md={6} lg={4}>
              <Card size="small">
                <Statistic
                  title={s.title}
                  value={s.value}
                  suffix={s.suffix}
                  precision={(s as { precision?: number }).precision}
                  valueStyle={(s as { valueStyle?: React.CSSProperties }).valueStyle}
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* Agent table */}
      <Card
        title={
          <Title level={5} style={{ margin: 0 }}>
            Agent performance — {agentRows.length} agents
            {queryParams.date_from && (
              <Text
                type="secondary"
                style={{ fontSize: 13, fontWeight: 400, marginLeft: 12 }}
              >
                {queryParams.date_from} → {queryParams.date_to || 'now'}
              </Text>
            )}
          </Title>
        }
        size="small"
      >
        <Table<AgentRow>
          dataSource={agentRows}
          columns={columns}
          rowKey="agent"
          loading={isLoading}
          pagination={{ pageSize: 50, hideOnSinglePage: true }}
          size="small"
          rowClassName={(row) =>
            (row.avg_score ?? 0) < 7 ? 'ant-table-row-danger' : ''
          }
        />
      </Card>
    </div>
  )
}
