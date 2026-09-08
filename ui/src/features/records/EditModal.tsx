import { Form, Input, Modal, Select, Switch, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { updateRecord } from './api'
import type { QARecord } from './types'

interface Props {
  record: QARecord
  onClose: () => void
  onSuccess: (updated: QARecord) => void
}

export default function EditModal({ record, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()

  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      updateRecord(record.id, {
        customer: values.customer as string,
        primary_operator: values.primary_operator as string,
        is_resolved: values.is_resolved as boolean,
        summary: values.summary as string,
        tags: values.tags as string[],
      }),
    onSuccess: (updated) => {
      message.success('Record updated')
      onSuccess(updated)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Update failed')
    },
  })

  return (
    <Modal
      title={`Edit — ${record.date}  |  ${record.primary_operator}  |  ${record.app}`}
      open
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
      okText="Save"
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          customer: record.customer,
          primary_operator: record.primary_operator,
          is_resolved: record.is_resolved,
          summary: record.summary || '',
          tags: record.tags || [],
        }}
        onFinish={(v) => mutation.mutate(v)}
      >
        <Form.Item name="customer" label="Customer">
          <Input />
        </Form.Item>

        <Form.Item name="primary_operator" label="Agent">
          <Input />
        </Form.Item>

        <Form.Item name="is_resolved" label="Resolved" valuePropName="checked">
          <Switch checkedChildren="Yes" unCheckedChildren="No" />
        </Form.Item>

        <Form.Item name="tags" label="Tags">
          <Select mode="tags" placeholder="Add or remove tags…" tokenSeparators={[',']} />
        </Form.Item>

        <Form.Item name="summary" label="Summary">
          <Input.TextArea rows={5} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
