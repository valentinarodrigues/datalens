import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Database, Search, Shield, Activity, ChevronRight,
  ChevronDown, Send, Bot, User, Clock, Zap,
  BarChart3, FileText, AlertTriangle, CheckCircle,
  XCircle, Layers, Cloud, Radio, Table2, PanelRight,
  Loader2, TrendingUp, DollarSign, Users,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Message, Persona, TraceData, GuardrailStatus, PlatformMetrics, ToolCall } from './types'

const PERSONAS: { label: Persona; icon: typeof Database; color: string; description: string }[] = [
  { label: 'Data Scientist', icon: BarChart3, color: 'text-purple-400', description: 'Schemas, quality, ML permissions' },
  { label: 'Data Engineer', icon: Database, color: 'text-blue-400', description: 'Access patterns, pipelines, SLAs' },
  { label: 'Product Owner', icon: Layers, color: 'text-emerald-400', description: 'Use cases, coverage, adoption' },
  { label: 'Procurement', icon: FileText, color: 'text-amber-400', description: 'Contracts, cost, renewals' },
  { label: 'Data Consumer', icon: Search, color: 'text-rose-400', description: 'What can I answer? How to access?' },
]

const ACCESS_TYPE_ICONS: Record<string, typeof Database> = {
  database: Database,
  saas_api: Cloud,
  datalake: Table2,
  sns_topic: Radio,
}

const SUGGESTED_QUERIES: Record<Persona, string[]> = {
  'Data Scientist': [
    'What credit data products are available for ML feature engineering?',
    'Show me the schema for CreditPulse Pro',
    'Can I use TransactIQ for training a spend prediction model?',
    'Which datasets have >95% completeness score?',
  ],
  'Data Engineer': [
    'How do I connect to the GeoMatrix datalake?',
    'What SNS topics can I subscribe to for real-time events?',
    'Show me access patterns for HealthInsights Pro',
    'Which products integrate with Airflow pipelines?',
  ],
  'Product Owner': [
    'Give me an overview of all third-party data products',
    'Which data products are most widely adopted across teams?',
    'What weather data can I use for a logistics product feature?',
    'Which datasets cover real-time market events?',
  ],
  'Procurement': [
    'Which contracts are up for renewal in 2026?',
    'What is the total annual spend across all data products?',
    'Compare CreditPulse Pro and HealthInsights Pro costs',
    'Does MarketPulse Events have auto-renewal enabled?',
  ],
  'Data Consumer': [
    'What data do we have about consumer spending patterns?',
    'How do I get access to weather data for my analysis?',
    'Can I use this credit data for my project?',
    'What brand monitoring data is available?',
  ],
}

// ── API ───────────────────────────────────────────────────────────────────────

async function sendChat(
  message: string,
  persona: Persona,
  history: { role: string; content: string }[],
) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, persona, conversation_history: history }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

async function fetchMetrics(): Promise<PlatformMetrics> {
  const res = await fetch('/api/metrics')
  if (!res.ok) throw new Error('Failed to fetch metrics')
  return res.json()
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PersonaSelector({
  selected,
  onChange,
}: {
  selected: Persona
  onChange: (p: Persona) => void
}) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-1 mb-2">
        Viewing as
      </p>
      {PERSONAS.map(({ label, icon: Icon, color, description }) => (
        <button
          key={label}
          onClick={() => onChange(label)}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all ${
            selected === label
              ? 'bg-slate-700 ring-1 ring-slate-500'
              : 'hover:bg-slate-800'
          }`}
        >
          <Icon size={16} className={color} />
          <div className="min-w-0">
            <div className={`text-sm font-medium ${selected === label ? 'text-slate-100' : 'text-slate-300'}`}>
              {label}
            </div>
            <div className="text-xs text-slate-500 truncate">{description}</div>
          </div>
          {selected === label && (
            <div className="ml-auto w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
          )}
        </button>
      ))}
    </div>
  )
}

function MetricsSidebar({ metrics }: { metrics: PlatformMetrics | null }) {
  if (!metrics) {
    return (
      <div className="space-y-2 animate-pulse">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="h-12 bg-slate-800 rounded-lg" />
        ))}
      </div>
    )
  }

  const stats = [
    {
      label: 'Products',
      value: metrics.total_products,
      icon: Layers,
      color: 'text-blue-400',
    },
    {
      label: 'Annual Spend',
      value: `$${(metrics.total_annual_spend_usd / 1000).toFixed(0)}K`,
      icon: DollarSign,
      color: 'text-amber-400',
    },
    {
      label: 'Teams Using',
      value: metrics.total_teams_using,
      icon: Users,
      color: 'text-emerald-400',
    },
    {
      label: 'Vendors',
      value: metrics.total_vendors,
      icon: TrendingUp,
      color: 'text-purple-400',
    },
  ]

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-1 mb-2">
        Portfolio
      </p>
      <div className="grid grid-cols-2 gap-2">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-slate-800/60 rounded-lg p-2.5">
            <Icon size={14} className={`${color} mb-1`} />
            <div className="text-lg font-bold text-slate-100 leading-none">{value}</div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Access types */}
      <div className="bg-slate-800/60 rounded-lg p-2.5 space-y-1">
        <p className="text-xs text-slate-500 font-medium mb-1.5">Access Types</p>
        {Object.entries(metrics.access_type_counts).map(([type, count]) => {
          const Icon = ACCESS_TYPE_ICONS[type] ?? Database
          const labels: Record<string, string> = {
            saas_api: 'SaaS API',
            database: 'Database',
            datalake: 'Datalake',
            sns_topic: 'SNS Topic',
          }
          return (
            <div key={type} className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Icon size={11} className="text-slate-400" />
                <span className="text-xs text-slate-400">{labels[type] ?? type}</span>
              </div>
              <span className="text-xs font-semibold text-slate-300">{count}</span>
            </div>
          )
        })}
      </div>

      {/* Expiring contracts alert */}
      {metrics.contracts_expiring_soon.length > 0 && (
        <div className="bg-amber-900/20 border border-amber-800/40 rounded-lg p-2.5">
          <div className="flex items-center gap-1.5 mb-1.5">
            <AlertTriangle size={12} className="text-amber-400" />
            <p className="text-xs text-amber-400 font-semibold">Contracts Expiring</p>
          </div>
          {metrics.contracts_expiring_soon.slice(0, 3).map(c => (
            <div key={c.name} className="text-xs text-amber-200/70 py-0.5">
              <span className="truncate block">{c.name}</span>
              <span className="text-amber-400/60">{c.renewal_date}</span>
              {!c.auto_renewal && (
                <span className="ml-1 text-red-400 font-medium">· Manual</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function GuardrailBadge({ guardrails }: { guardrails: GuardrailStatus }) {
  const allPassed = guardrails.input_passed && guardrails.output_passed
  if (allPassed) return null
  return (
    <div className="mt-2 flex items-start gap-1.5 bg-red-900/20 border border-red-800/40 rounded-lg px-2 py-1.5">
      <Shield size={12} className="text-red-400 mt-0.5 shrink-0" />
      <div>
        <p className="text-xs font-semibold text-red-400">Guardrail triggered</p>
        {[...guardrails.input_violations, ...guardrails.output_violations].map((v, i) => (
          <p key={i} className="text-xs text-red-300/70">{v}</p>
        ))}
      </div>
    </div>
  )
}

function TracePanel({ trace }: { trace: TraceData }) {
  const [expanded, setExpanded] = useState(false)

  const TOOL_COLORS: Record<string, string> = {
    search_catalog: 'text-blue-400',
    get_product_schema: 'text-purple-400',
    get_quality_metrics: 'text-emerald-400',
    check_legal_compliance: 'text-red-400',
    get_contract_info: 'text-amber-400',
    get_usage_statistics: 'text-cyan-400',
    get_access_patterns: 'text-indigo-400',
    compare_products: 'text-rose-400',
    get_sample_queries: 'text-teal-400',
    get_platform_overview: 'text-slate-400',
  }

  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Activity size={13} className="text-blue-400" />
          <span className="text-xs font-semibold text-slate-300">
            Agent Trace
          </span>
          <span className="text-xs text-slate-500 font-mono">#{trace.trace_id}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">
            {trace.tool_calls.length} tools · {trace.wall_time_ms}ms
          </span>
          {expanded ? (
            <ChevronDown size={13} className="text-slate-500" />
          ) : (
            <ChevronRight size={13} className="text-slate-500" />
          )}
        </div>
      </button>

      {/* Quick stats row — always visible */}
      <div className="flex items-center gap-3 px-3 pb-2 border-b border-slate-800">
        <div className="flex items-center gap-1">
          <Clock size={11} className="text-slate-500" />
          <span className="text-xs text-slate-500">{trace.wall_time_ms}ms</span>
        </div>
        <div className="flex items-center gap-1">
          <Zap size={11} className="text-slate-500" />
          <span className="text-xs text-slate-500">
            {trace.total_tokens.total?.toLocaleString() ?? '—'} tokens
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Bot size={11} className="text-slate-500" />
          <span className="text-xs text-slate-500">{trace.llm_call_count} LLM calls</span>
        </div>
      </div>

      {/* Tool calls list */}
      {expanded && (
        <div className="px-3 py-2 space-y-1.5">
          {trace.tool_calls.length === 0 ? (
            <p className="text-xs text-slate-600 italic">No tool calls</p>
          ) : (
            trace.tool_calls.map((tc: ToolCall, i) => (
              <div key={i} className="flex items-center gap-2 group">
                <CheckCircle size={11} className="text-emerald-500 shrink-0" />
                <span className={`text-xs font-mono font-medium ${TOOL_COLORS[tc.tool] ?? 'text-slate-400'}`}>
                  {tc.tool}
                </span>
                <span className="text-xs text-slate-600 ml-auto">{tc.latency_ms}ms</span>
              </div>
            ))
          )}

          {/* Token breakdown */}
          {trace.total_tokens.total > 0 && (
            <div className="mt-2 pt-2 border-t border-slate-800 grid grid-cols-3 gap-1">
              {[
                { label: 'In', value: trace.total_tokens.input },
                { label: 'Out', value: trace.total_tokens.output },
                { label: 'Total', value: trace.total_tokens.total },
              ].map(({ label, value }) => (
                <div key={label} className="text-center">
                  <div className="text-xs font-semibold text-slate-300">{value?.toLocaleString()}</div>
                  <div className="text-xs text-slate-600">{label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-1 ${
          isUser ? 'bg-blue-600' : 'bg-slate-700'
        }`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} className="text-blue-400" />}
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div
          className={`px-4 py-3 rounded-2xl ${
            isUser
              ? 'bg-blue-600 text-white rounded-tr-sm'
              : message.blocked
              ? 'bg-red-900/30 border border-red-800/50 rounded-tl-sm'
              : 'bg-slate-800 rounded-tl-sm'
          }`}
        >
          {isUser ? (
            <p className="text-sm">{message.content}</p>
          ) : (
            <div className="prose-datalens">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* Timestamp */}
        <span className="text-xs text-slate-600 px-1">
          {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>

        {/* Guardrail warning */}
        {message.guardrails && !message.guardrails.input_passed && (
          <GuardrailBadge guardrails={message.guardrails} />
        )}

        {/* Trace panel (assistant messages only) */}
        {!isUser && message.trace && message.trace.tool_calls.length > 0 && (
          <div className="w-full mt-1">
            <TracePanel trace={message.trace} />
          </div>
        )}
      </div>
    </div>
  )
}

function SuggestedQueries({
  persona,
  onSelect,
}: {
  persona: Persona
  onSelect: (q: string) => void
}) {
  const queries = SUGGESTED_QUERIES[persona]
  return (
    <div className="px-4 py-3 border-t border-slate-800">
      <p className="text-xs text-slate-600 mb-2 font-medium">Suggested for {persona}</p>
      <div className="flex flex-wrap gap-1.5">
        {queries.map(q => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 px-2.5 py-1.5 rounded-lg transition-colors border border-slate-700/50 text-left"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [persona, setPersona] = useState<Persona>('Data Scientist')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null)
  const [showTrace, setShowTrace] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Fetch platform metrics on load
  useEffect(() => {
    fetchMetrics()
      .then(setMetrics)
      .catch(e => console.error('Metrics fetch failed:', e))
  }, [])

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle persona change — show context message
  const handlePersonaChange = useCallback((p: Persona) => {
    setPersona(p)
    setMessages([])
  }, [])

  const handleSend = useCallback(
    async (text?: string) => {
      const messageText = (text ?? input).trim()
      if (!messageText || loading) return

      setInput('')
      setError(null)

      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: messageText,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, userMsg])
      setLoading(true)

      // Build history for API (exclude the message just added)
      const history = messages.map(m => ({ role: m.role, content: m.content }))

      try {
        const data = await sendChat(messageText, persona, history)

        const assistantMsg: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: data.response,
          timestamp: new Date(),
          trace: data.trace,
          guardrails: data.guardrails,
          blocked: data.blocked,
        }
        setMessages(prev => [...prev, assistantMsg])
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        if (msg.includes('invalid x-api-key') || msg.includes('authentication_error') || msg.includes('401')) {
          setError('Invalid Anthropic API key. Add your key from console.anthropic.com to backend/.env as ANTHROPIC_API_KEY=sk-ant-..., then restart the backend.')
        } else if (msg.includes('fetch') || msg.includes('NetworkError') || msg.includes('Failed to fetch')) {
          setError('Cannot reach the backend. Make sure it is running: cd backend && .venv/bin/uvicorn main:app --port 8000')
        } else {
          setError(`Agent error: ${msg}`)
        }
      } finally {
        setLoading(false)
        inputRef.current?.focus()
      }
    },
    [input, loading, messages, persona],
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-950">
      {/* ── Header ── */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-900/80 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Search size={16} className="text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-100 leading-none">DataLens</h1>
            <p className="text-xs text-slate-500 leading-none mt-0.5">Third-party data discovery</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-emerald-900/30 border border-emerald-800/40 px-2.5 py-1 rounded-full">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-emerald-400 font-medium">8 products live</span>
          </div>
          <button
            onClick={() => setShowTrace(s => !s)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors border ${
              showTrace
                ? 'bg-blue-900/30 border-blue-800/40 text-blue-400'
                : 'border-slate-700 text-slate-500 hover:text-slate-300'
            }`}
          >
            <PanelRight size={12} />
            Trace
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left Sidebar ── */}
        <aside className="w-56 shrink-0 border-r border-slate-800 bg-slate-900/50 flex flex-col overflow-y-auto">
          <div className="p-3 space-y-5">
            <PersonaSelector selected={persona} onChange={handlePersonaChange} />
            <MetricsSidebar metrics={metrics} />
          </div>
        </aside>

        {/* ── Chat Area ── */}
        <main className="flex flex-col flex-1 overflow-hidden">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            {isEmpty ? (
              /* Welcome state */
              <div className="flex flex-col items-center justify-center h-full text-center gap-4">
                <div className="w-16 h-16 rounded-2xl bg-blue-600/20 border border-blue-600/30 flex items-center justify-center">
                  <Search size={28} className="text-blue-400" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-200">Welcome to DataLens</h2>
                  <p className="text-sm text-slate-500 mt-1 max-w-md">
                    Ask me about third-party data products — schemas, quality, contracts,
                    access patterns, and more. Viewing as <span className="text-slate-300 font-medium">{persona}</span>.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 max-w-lg w-full mt-2">
                  {[
                    { icon: Database, label: 'DB & Datalake', sub: '4 products', color: 'text-blue-400' },
                    { icon: Cloud, label: 'SaaS APIs', sub: '3 products', color: 'text-purple-400' },
                    { icon: Radio, label: 'SNS Streams', sub: '1 product', color: 'text-emerald-400' },
                    { icon: Shield, label: 'Guardrails active', sub: 'PII + legal', color: 'text-amber-400' },
                  ].map(({ icon: Icon, label, sub, color }) => (
                    <div key={label} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-3 flex items-center gap-3">
                      <Icon size={18} className={color} />
                      <div>
                        <p className="text-sm font-medium text-slate-200">{label}</p>
                        <p className="text-xs text-slate-500">{sub}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              messages.map(msg => <ChatMessage key={msg.id} message={msg} />)
            )}

            {/* Loading indicator */}
            {loading && (
              <div className="flex gap-3">
                <div className="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center shrink-0 mt-1">
                  <Bot size={14} className="text-blue-400" />
                </div>
                <div className="bg-slate-800 px-4 py-3 rounded-2xl rounded-tl-sm">
                  <div className="flex items-center gap-2">
                    <Loader2 size={14} className="text-blue-400 animate-spin" />
                    <span className="text-sm text-slate-400">Agent working…</span>
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 bg-red-900/20 border border-red-800/40 rounded-xl px-4 py-3">
                <XCircle size={16} className="text-red-400 shrink-0" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Suggested queries (empty state) */}
          {isEmpty && (
            <SuggestedQueries persona={persona} onSelect={q => handleSend(q)} />
          )}

          {/* Input bar */}
          <div className="border-t border-slate-800 bg-slate-900/50 px-4 py-3">
            <div className="flex items-end gap-2 bg-slate-800 rounded-xl border border-slate-700 px-3 py-2 focus-within:border-blue-500/50 transition-colors">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`Ask as ${persona}… (Shift+Enter for new line)`}
                rows={1}
                className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none leading-relaxed max-h-32"
                style={{ minHeight: '24px' }}
                onInput={e => {
                  const t = e.currentTarget
                  t.style.height = 'auto'
                  t.style.height = `${Math.min(t.scrollHeight, 128)}px`
                }}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                className="w-8 h-8 flex items-center justify-center rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                {loading ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Send size={15} />
                )}
              </button>
            </div>
            <div className="flex items-center justify-between mt-1.5 px-1">
              <div className="flex items-center gap-1.5">
                <Shield size={11} className="text-slate-600" />
                <span className="text-xs text-slate-600">PII & legal guardrails active</span>
              </div>
              <span className="text-xs text-slate-700">Enter to send</span>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
