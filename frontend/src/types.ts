export type Persona = 'Data Scientist' | 'Data Engineer' | 'Product Owner' | 'Procurement' | 'Data Consumer'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  trace?: TraceData
  guardrails?: GuardrailStatus
  blocked?: boolean
}

export interface ToolCall {
  tool: string
  latency_ms: number
  output_preview: string
  output_keys: string[]
}

export interface TraceData {
  trace_id: string
  persona: string
  tool_calls: ToolCall[]
  llm_call_count: number
  total_tokens: { input: number; output: number; total: number }
  agent_latency_ms: number
  wall_time_ms: number
  tools_used: string[]
}

export interface GuardrailStatus {
  input_passed: boolean
  input_violations: string[]
  output_passed: boolean
  output_violations: string[]
}

export interface PlatformMetrics {
  total_products: number
  total_vendors: number
  total_annual_spend_usd: number
  total_teams_using: number
  total_users: number
  access_type_counts: Record<string, number>
  domain_counts: Record<string, number>
  contracts_expiring_soon: Array<{ name: string; renewal_date: string; auto_renewal: boolean }>
}
