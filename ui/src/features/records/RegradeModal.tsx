import { useState } from 'react'
import { Input, Modal, Spin, Tag, Typography, message } from 'antd'
import { SyncOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { regradeRecord } from './api'
import type { QARecord } from './types'

interface Props {
  record: QARecord
  onClose: () => void
  onSuccess: (updated: QARecord) => void
}

const { Text, Paragraph } = Typography

// Gợi ý nhanh để click vào điền
const QUICK_HINTS = [
  'Khách đã cho review 5 sao',
  'Khách đã cho review 4 sao',
  'Vấn đề chưa giải quyết xong do khách offline',
  'Agent chỉ phụ trách phần cuối của chat',
  'Tin nhắn tự động/bot chiếm phần đầu',
  'Khách bực bội, agent xử lý tốt',
  'Case cần chuyển dev, không phải lỗi agent',
]

export default function RegradeModal({ record, onClose, onSuccess }: Props) {
  const [feedback, setFeedback] = useState('')

  const mutation = useMutation({
    mutationFn: () => regradeRecord(record.id, feedback.trim() || undefined),
    onSuccess: (updated) => {
      const prev = record.grading?.final_score_10?.toFixed(2)
      const next = updated.grading?.final_score_10?.toFixed(2)
      const changed = prev !== next
      message.success(
        changed ? `Chấm lại xong: ${prev} → ${next}/10` : `Chấm lại xong: ${next}/10 (không đổi)`,
        4,
      )
      onSuccess(updated)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Re-grading failed')
    },
  })

  const appendHint = (hint: string) => {
    setFeedback((prev) => {
      const trimmed = prev.trim()
      return trimmed ? `${trimmed}\n${hint}` : hint
    })
  }

  return (
    <Modal
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SyncOutlined style={{ color: '#6366f1' }} />
          Chấm lại — <strong>{record.primary_operator}</strong> · {record.date} ·{' '}
          <Tag color={record.app === 'DECO' ? 'purple' : 'cyan'} style={{ margin: 0 }}>
            {record.app}
          </Tag>
        </span>
      }
      open
      onCancel={onClose}
      onOk={() => mutation.mutate()}
      confirmLoading={mutation.isPending}
      okText={mutation.isPending ? 'Đang chấm…' : 'Chấm lại'}
      okButtonProps={{ icon: <SyncOutlined />, style: { background: '#6366f1', borderColor: '#6366f1' } }}
      width={560}
    >
      <Spin spinning={mutation.isPending} tip="Đang gọi AI…">
        {/* Current score info */}
        <div style={{
          background: '#f8fafc', border: '1px solid #e2e8f0',
          borderRadius: 8, padding: '10px 14px', marginBottom: 14,
          display: 'flex', gap: 20,
        }}>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>Điểm hiện tại</Text>
            <div style={{ fontWeight: 800, fontSize: 20, color: '#0f172a', letterSpacing: -0.5 }}>
              {record.grading?.final_score_10?.toFixed(2) ?? '?'}<span style={{ fontSize: 13, color: '#94a3b8' }}>/10</span>
            </div>
          </div>
          <div style={{ width: 1, background: '#e2e8f0' }} />
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>Tổng 20pt</Text>
            <div style={{ fontWeight: 700, fontSize: 16, color: '#334155' }}>
              {record.grading?.total_score_20?.toFixed(2) ?? '?'}
            </div>
          </div>
        </div>

        {/* Feedback label */}
        <Paragraph style={{ marginBottom: 6, fontSize: 13 }}>
          <Text strong>Góp ý bổ sung</Text>{' '}
          <Text type="secondary">(không bắt buộc)</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            Thêm thông tin để AI cân nhắc khi chấm lại — không thay prompt, chỉ bổ sung context.
          </Text>
        </Paragraph>

        {/* Quick hints */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
          {QUICK_HINTS.map((hint) => (
            <Tag
              key={hint}
              style={{ cursor: 'pointer', fontSize: 11, borderStyle: 'dashed' }}
              onClick={() => appendHint(hint)}
            >
              + {hint}
            </Tag>
          ))}
        </div>

        {/* Textarea */}
        <Input.TextArea
          rows={4}
          placeholder="VD: Khách đã cho review 5 sao · Agent chỉ phụ trách phần cuối chat · Case cần chuyển dev..."
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          disabled={mutation.isPending}
          style={{ borderRadius: 8, fontSize: 13 }}
        />
      </Spin>
    </Modal>
  )
}
