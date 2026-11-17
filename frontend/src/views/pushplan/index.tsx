import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/pushplan'
const columns = [
  "方案编号",
  "推送内容",
  "目标人群",
  "推送渠道",
  "推送时间",
  "频控策略",
  "AB分组标识",
  "预计触达量",
  "实时决策状态"
]
const actions = [
  "提交方案审批",
  "启动推送",
  "撤回推送"
]
const statuses = [
  "草稿",
  "方案审批中",
  "执行中",
  "已完成",
  "已撤回"
]
const stats = [
  {
    "label": "推送方案总数",
    "value": 0
  },
  {
    "label": "执行中方案",
    "value": 0
  },
  {
    "label": "已完成方案",
    "value": 0
  }
]

type Row = Record<string, string | number | null>
type AnyRecord = Record<string, any>

export default function PushplanView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [detailsPlan, setDetailsPlan] = useState<Row | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('推送方案列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '推送计划列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('推送计划动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '推送计划操作失败')
    }
  }

  if (detailsPlan) {
    return (
      <PendingDetailsPanel
        plan={detailsPlan}
        onBack={() => {
          setDetailsPlan(null)
          void reload()
        }}
      />
    )
  }

  return (
    <section className="page" data-module="pushplan">
      <header className="page-head">
        <div>
          <h2>推送计划管理</h2>
          <p className="page-desc">管理运营消息的推送计划，包括人群定向、渠道选择和频控策略。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('推送方案登记入口尚未接入审批流')}>
            登记推送方案
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出推送计划清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] || '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => setDetailsPlan(row)}>
                  待处理明细
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无推送计划数据，可先登记推送方案</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条推送计划记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}

function PendingDetailsPanel({ plan, onBack }: { plan: Row; onBack: () => void }) {
  const [details, setDetails] = useState<AnyRecord | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  const load = useCallback(async () => {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${plan.id}/pending-details`)
      if (!response.ok) {
        throw new Error('推送计划待处理明细读取失败')
      }
      setDetails(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '推送计划待处理明细读取失败')
    }
  }, [plan.id])

  useEffect(() => {
    void load()
  }, [load])

  const checklists: AnyRecord[] = details?.核对表 ?? []
  const batches: AnyRecord[] = details?.批次 ?? []

  return (
    <section className="page" data-module="pushplan" data-verify="186a65f3">
      <header className="page-head">
        <div>
          <h2>待处理明细 · {String(plan.方案编号 ?? '')}</h2>
          <p className="page-desc">
            登记在案的频控窗口裁量核对表与推送批次现状；实时决策状态已同步到推送计划清单。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={onBack}>
            返回列表
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">方案状态</span>
          <strong className="stat-value">{details?.方案状态 ?? '—'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">实时决策状态</span>
          <strong className="stat-value">{details?.实时决策状态 || '—'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">已登记核对表</span>
          <strong className="stat-value">{checklists.length}</strong>
        </article>
      </div>

      <section className="detail-panel">
        <h3 className="section-title">频控窗口裁量核对表（可用于结算）</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>核对编号</th>
              <th>关联规则</th>
              <th>分流批次</th>
              <th>数据版本</th>
              <th>快照版本</th>
              <th>待发送人数</th>
              <th>结算状态</th>
              <th>登记时间</th>
            </tr>
          </thead>
          <tbody>
            {checklists.map((item) => (
              <tr key={String(item.核对编号)}>
                <td>{item.核对编号}</td>
                <td>{item.关联规则}</td>
                <td>{item.分流批次}</td>
                <td>v{item.数据版本}</td>
                <td>{item.快照版本}</td>
                <td>{item.待发送人数}</td>
                <td><span className="tag ok">{item.结算状态}</span></td>
                <td>{item.登记时间 ?? '—'}</td>
              </tr>
            ))}
            {checklists.length === 0 && (
              <tr><td className="empty-state" colSpan={8}>暂无频控窗口裁量核对表</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="detail-panel">
        <h3 className="section-title">推送批次现状</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>批次号</th>
              <th>关联规则</th>
              <th>AB分组标识</th>
              <th>数据版本</th>
              <th>人群快照版本</th>
              <th>待发送人数</th>
              <th>名单状态</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => (
              <tr key={String(batch.批次号)}>
                <td>{batch.批次号}</td>
                <td>{batch.关联规则}</td>
                <td>{batch.AB分组标识}</td>
                <td>v{batch.数据版本}</td>
                <td>{batch.人群快照版本}</td>
                <td>{batch.待发送人数}</td>
                <td>
                  {(batch.用户名单 ?? []).map((user: AnyRecord) => (
                    <span key={String(user.用户ID)} className={`tag ${user.状态 === '待发送' ? '' : 'warn'}`}>
                      {user.用户ID}·{user.状态}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
            {batches.length === 0 && (
              <tr><td className="empty-state" colSpan={7}>暂无推送批次</td></tr>
            )}
          </tbody>
        </table>
        {errorMessage && <p className="error-text">{errorMessage}</p>}
      </section>
    </section>
  )
}
