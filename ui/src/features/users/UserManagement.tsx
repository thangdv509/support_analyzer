import { useState } from 'react'
import {
  Avatar,
  Button,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SyncOutlined,
  UserOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addUser,
  fetchUsers,
  removeUser,
  updateRole,
  type Role,
  type UserRecord,
} from './api'
import { useAuth } from '@/features/auth/AuthContext'

const http = axios.create({ baseURL: '/api', withCredentials: true })

const { Text } = Typography

const ROLE_COLOR: Record<Role, string> = {
  admin:   '#6366f1',
  manager: '#0891b2',
  support: '#16a34a',
}

const ROLE_OPTIONS: { label: string; value: Role }[] = [
  { label: 'Admin',   value: 'admin' },
  { label: 'Manager', value: 'manager' },
  { label: 'Support', value: 'support' },
]

export default function UserManagement() {
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [editUser, setEditUser] = useState<UserRecord | null>(null)
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers,
    staleTime: 30_000,
  })

  const syncMut = useMutation({
    mutationFn: () => http.post('/crisp/sync-agents').then(r => r.data),
    onSuccess: (res) => {
      message.success(`Sync xong: +${res.added} mới, ${res.updated} cập nhật`)
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['agent-map'] })
    },
    onError: () => message.error('Sync thất bại'),
  })

  const addMut = useMutation({
    mutationFn: ({ email, role }: { email: string; role: Role }) => addUser(email, role),
    onSuccess: () => {
      message.success('User added')
      qc.invalidateQueries({ queryKey: ['users'] })
      setAddOpen(false)
      form.resetFields()
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Failed to add user')
    },
  })

  const roleMut = useMutation({
    mutationFn: ({ email, role }: { email: string; role: Role }) => updateRole(email, role),
    onSuccess: () => {
      message.success('Role updated')
      qc.invalidateQueries({ queryKey: ['users'] })
      setEditUser(null)
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Failed to update role')
    },
  })

  const deleteMut = useMutation({
    mutationFn: removeUser,
    onSuccess: () => {
      message.success('User removed')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || 'Failed to remove user')
    },
  })

  // Role options based on viewer's role
  const allowedRoles = me?.role === 'admin'
    ? ROLE_OPTIONS
    : ROLE_OPTIONS.filter(r => r.value === 'support')

  const isAdmin   = me?.role === 'admin'
  const isManager = me?.role === 'manager'

  const columns = [
    {
      title: 'User',
      key: 'user',
      render: (r: UserRecord) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {r.picture
            ? <img src={r.picture} alt="" style={{ width: 32, height: 32, borderRadius: '50%' }} />
            : <Avatar size={32} icon={<UserOutlined />} />
          }
          <div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>
              {(r as UserRecord & { nickname?: string }).nickname?.trim() || r.name}
            </div>
            {(r as UserRecord & { nickname?: string }).nickname?.trim() && (
              <div style={{ fontSize: 11, color: '#64748b' }}>{r.name}</div>
            )}
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{r.email}</div>
          </div>
          {r.email === me?.email && (
            <Tag style={{ fontSize: 10, padding: '0 5px' }}>You</Tag>
          )}
        </div>
      ),
    },
    {
      title: 'Role',
      dataIndex: 'role',
      key: 'role',
      width: 110,
      render: (role: Role) => (
        <Tag style={{
          background: `${ROLE_COLOR[role]}18`,
          color: ROLE_COLOR[role],
          border: `1px solid ${ROLE_COLOR[role]}44`,
          fontWeight: 600,
          fontSize: 12,
        }}>
          {role.charAt(0).toUpperCase() + role.slice(1)}
        </Tag>
      ),
    },
    {
      title: 'Added by',
      dataIndex: 'added_by',
      key: 'added_by',
      width: 160,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: 'Last login',
      dataIndex: 'last_login',
      key: 'last_login',
      width: 130,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {v ? new Date(v).toLocaleDateString('vi-VN') : '—'}
        </Text>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 80,
      render: (r: UserRecord) => {
        const isSelf = r.email === me?.email
        return (
          <div style={{ display: 'flex', gap: 4 }}>
            {isAdmin && (
              <Tooltip title="Edit role">
                <Button
                  size="small" type="text"
                  icon={<EditOutlined />}
                  onClick={() => {
                    setEditUser(r)
                    editForm.setFieldsValue({ role: r.role })
                  }}
                />
              </Tooltip>
            )}
            {isAdmin && !isSelf && (
              <Popconfirm
                title="Remove this user?"
                description={`${r.name} (${r.email}) will lose access.`}
                okType="danger"
                okText="Remove"
                onConfirm={() => deleteMut.mutate(r.email)}
              >
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            )}
          </div>
        )
      },
    },
  ]

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <Text strong style={{ fontSize: 15 }}>User Management</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>{users.length} users</Text>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {isAdmin && (
            <Popconfirm
              title="Sync agents từ Crisp?"
              description="Sẽ thêm tất cả operators Crisp chưa có vào danh sách với role Support."
              okText="Sync"
              onConfirm={() => syncMut.mutate()}
            >
              <Button size="small" icon={<SyncOutlined />} loading={syncMut.isPending}>
                Sync from Crisp
              </Button>
            </Popconfirm>
          )}
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setAddOpen(true)}
          >
            Add user
          </Button>
        </div>
      </div>

      {/* Table */}
      <div style={{ background: '#fff', borderRadius: 10, boxShadow: '0 1px 4px #0001', overflow: 'hidden' }}>
        <Table<UserRecord>
          dataSource={users}
          columns={columns}
          rowKey="email"
          loading={isLoading}
          size="small"
          pagination={false}
        />
      </div>

      {/* Add user modal */}
      <Modal
        title="Add user"
        open={addOpen}
        onCancel={() => { setAddOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        confirmLoading={addMut.isPending}
        okText="Add"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={v => addMut.mutate({ email: v.email.trim().toLowerCase(), role: v.role })}
        >
          <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
            <Input placeholder="user@secomus.com" />
          </Form.Item>
          <Form.Item name="role" label="Role" rules={[{ required: true }]} initialValue="support">
            <Select options={allowedRoles} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit role modal */}
      {editUser && (
        <Modal
          title={`Edit role — ${editUser.name}`}
          open
          onCancel={() => setEditUser(null)}
          onOk={() => editForm.submit()}
          confirmLoading={roleMut.isPending}
          okText="Save"
        >
          <Form
            form={editForm}
            layout="vertical"
            onFinish={v => roleMut.mutate({ email: editUser.email, role: v.role })}
          >
            <Form.Item name="role" label="Role" rules={[{ required: true }]}>
              <Select options={ROLE_OPTIONS} />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  )
}
