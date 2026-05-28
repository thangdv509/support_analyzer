import { Form, InputNumber, Modal, Typography, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { updateRecord } from '../api'
import type { QARecord } from '../types'
import { CRITERIA_KEYS, CRITERIA_LABELS, CRITERIA_MAX, type CriterionKey } from '../types'

interface Props {
  record: QARecord
  onClose: () => void
  onSuccess: (updated: QARecord) => void
}

const { Text } = Typography

export default function ScoreEditModal({ record, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()

  const mutation = useMutation({
    mutationFn: async (values: Record<string, number>) => {
      const criteria = { ...record.grading?.criteria } as Record<
        string,
        { score: number; justification: string }
      >
      let total = 0
      for (const key of CRITERIA_KEYS) {
        const raw = values[key] ?? 0
        const capped = Math.min(Math.max(raw, 0), CRITERIA_MAX[key as CriterionKey])
        criteria[key] = { ...(criteria[key] || {}), score: capped } as {
          score: number
          justification: string
        }
        total += capped
      }
      const updatedGrading = {
        ...record.grading,
        criteria: criteria as unknown as import('../types').Criteria,
        total_score_20: Math.round(total * 100) / 100,
        final_score_10: Math.round((total / 2) * 100) / 100,
      }
      return updateRecord(record.id, { grading: updatedGrading })
    },
    onSuccess: (updated) => {
      message.success(
        `Scores saved — ${updated.grading?.final_score_10?.toFixed(2)}/10`,
      )
      onSuccess(updated)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Save failed')
    },
  })

  const initialValues = CRITERIA_KEYS.reduce<Record<string, number>>(
    (acc, key) => ({ ...acc, [key]: record.grading?.criteria?.[key]?.score ?? 0 }),
    {},
  )

  return (
    <Modal
      title={`Sửa điểm — ${record.primary_operator} | ${record.date} | ${record.app}`}
      open
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
      okText="Lưu điểm"
      width={720}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={(v) => mutation.mutate(v as Record<string, number>)}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '4px 24px',
          }}
        >
          {CRITERIA_KEYS.map((key) => {
            const current = record.grading?.criteria?.[key]?.score
            const max = CRITERIA_MAX[key as CriterionKey]
            const deducted = current != null && current < max
            return (
              <Form.Item
                key={key}
                name={key}
                label={
                  <span>
                    <Text strong style={{ fontSize: 13 }}>
                      {CRITERIA_LABELS[key as CriterionKey]}
                    </Text>
                    <Text
                      type="secondary"
                      style={{ fontSize: 12, marginLeft: 6 }}
                    >
                      (max {max})
                    </Text>
                    {deducted && (
                      <Text
                        type="danger"
                        style={{ fontSize: 11, marginLeft: 6 }}
                      >
                        was {current}
                      </Text>
                    )}
                  </span>
                }
                style={{ marginBottom: 8 }}
              >
                <InputNumber
                  min={0}
                  max={max}
                  step={0.25}
                  precision={2}
                  style={{ width: '100%' }}
                  status={deducted ? 'warning' : undefined}
                />
              </Form.Item>
            )
          })}
        </div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          Lưu ý: total_score_20 và final_score_10 sẽ được tính lại tự động.
        </Text>
      </Form>
    </Modal>
  )
}
