import { Divider, Modal, Tag, Typography } from 'antd'
import type { QARecord } from '../types'
import { CRITERIA_KEYS, CRITERIA_LABELS, CRITERIA_MAX } from '../types'
import MarkdownText from './MarkdownText'

interface Props {
  record: QARecord
  onClose: () => void
}

const { Text, Paragraph, Title } = Typography

function criteriaColor(score: number, max: number) {
  const r = score / max
  if (r >= 1) return '#52c41a'
  if (r >= 0.7) return '#faad14'
  return '#ff4d4f'
}

export default function DetailModal({ record, onClose }: Props) {
  const criteria = record.grading?.criteria as unknown as Record<
    string,
    { score: number; justification: string }
  >

  return (
    <Modal
      title={
        <span>
          Detail — {record.date} | {record.primary_operator} | {record.app} |{' '}
          <strong>{record.grading?.final_score_10?.toFixed(2) ?? '?'}/10</strong>
        </span>
      }
      open
      onCancel={onClose}
      footer={null}
      width={860}
      style={{ top: 20 }}
      styles={{ body: { maxHeight: '80vh', overflowY: 'auto' } }}
    >
      {/* Meta */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginBottom: 12 }}>
        <Text type="secondary">Session: <Text code>{record.session_id}</Text></Text>
        <Text type="secondary">Customer: <Text strong>{record.customer}</Text></Text>
        <Text type="secondary">
          Status:{' '}
          <Tag color={record.is_resolved ? 'success' : 'default'}>
            {record.is_resolved ? '✓ Resolved' : 'Open'}
          </Tag>
        </Text>
        {record.crisp_url && (
          <a href={record.crisp_url} target="_blank" rel="noreferrer">
            Open in Crisp ↗
          </a>
        )}
      </div>

      {/* Tags */}
      {record.tags?.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {record.tags.map((t, i) => (
            <Tag key={i}>{t}</Tag>
          ))}
        </div>
      )}

      {/* Summary */}
      {record.summary && (
        <>
          <Title level={5} style={{ marginBottom: 4 }}>Summary</Title>
          <div style={{ background: '#f6f8fa', padding: '8px 12px', borderRadius: 4 }}>
            <MarkdownText text={record.summary} />
          </div>
        </>
      )}

      {/* Overall summary from grading */}
      {record.grading?.overall_summary && (
        <>
          <Title level={5} style={{ marginBottom: 4 }}>Overall grading summary</Title>
          <div style={{ background: '#f6f8fa', padding: '8px 12px', borderRadius: 4 }}>
            <MarkdownText text={record.grading.overall_summary} />
          </div>
        </>
      )}

      <Divider style={{ margin: '12px 0' }} />

      {/* Criteria */}
      <Title level={5} style={{ marginBottom: 8 }}>
        Criteria — total {record.grading?.total_score_20?.toFixed(2) ?? '?'}/20 → {record.grading?.final_score_10?.toFixed(2) ?? '?'}/10
      </Title>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))',
          gap: 8,
        }}
      >
        {CRITERIA_KEYS.map((key) => {
          const c = criteria?.[key]
          if (!c) return null
          const max = CRITERIA_MAX[key]
          const color = criteriaColor(c.score, max)
          const isDeducted = c.score < max
          return (
            <div
              key={key}
              style={{
                border: `1px solid ${isDeducted ? '#ffccc7' : '#d9f7be'}`,
                background: isDeducted ? '#fff2f0' : '#f6ffed',
                borderRadius: 6,
                padding: '8px 12px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text strong style={{ fontSize: 13 }}>
                  {CRITERIA_LABELS[key]}
                </Text>
                <Text strong style={{ color, fontSize: 13 }}>
                  {c.score}/{max}
                </Text>
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {c.justification}
              </Text>
            </div>
          )
        })}
      </div>

      <Divider style={{ margin: '12px 0' }} />

      {/* Transcript */}
      <Title level={5} style={{ marginBottom: 4 }}>Transcript</Title>
      <pre
        style={{
          whiteSpace: 'pre-wrap',
          background: '#1e1e2e',
          color: '#cdd6f4',
          padding: '12px 16px',
          borderRadius: 6,
          fontSize: 12,
          lineHeight: 1.6,
          maxHeight: 360,
          overflowY: 'auto',
        }}
      >
        {record.transcript || '(no transcript)'}
      </pre>
    </Modal>
  )
}
