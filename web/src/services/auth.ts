/** UserOut — 用户信息类型 (P0-19: 从主项目复制, 供 auth store 使用) */
export interface UserOut {
  id: string
  email: string | null
  phone: string | null
  display_name: string
  avatar_url: string
  role: string
  status: string
  tenant_id: string | null
  last_login_at: string | null
  created_at: string
}
