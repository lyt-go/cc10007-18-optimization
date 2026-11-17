import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/realtime'
const columns = [
  "规则编号",
  "触发事件",
  "决策条件",
  "执行动作",
  "冷却时间秒",
  "优先级",
  "分流比例",
  "生效时段"
]
const actions = [
  "提交规则评审",
  "生效规则",
  "暂停规则"
]
const statuses = [
  "草稿",
  "规则评审中",
  "已生效",
  "已暂停"
]
const stats = [
  {
    "label": "决策规则总数",
    "value": 0
  },
  {
    "label": "已生效规则",
    "value": 0
  },
  {
    "label": "评审中规则",
    "value": 0
  }
]

type Row = Record<string, string | number | null>
type AnyRecord = Record<string, any>

export default function RealtimeView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [discretionRule, setDiscretionRule] = useState<Row | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('决策规则列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '实时决策列表读取失败')
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
        throw new Error('实时决策动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '实时决策操作失败')
    }
  }

  if (discretionRule) {
    return (
      <DiscretionPanel
        rule={discretionRule}
        onBack={() => {
          setDiscretionRule(null)
          void reload()
        }}
      />
    )
  }

  return (
    <section className="page" data-module="realtime">
      <header className="page-head">
        <div>
          <h2>实时决策管理</h2>
          <p className="page-desc">配置实时运营决策规则，基于用户实时行为触发个性化动作。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('决策规则登记入口尚未接入审批流')}>
            登记决策规则
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出实时决策清单
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
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => setDiscretionRule(row)}>
                  频控窗口裁量
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无实时决策数据，可先登记决策规则</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条实时决策记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}

function DiscretionPanel({ rule, onBack }: { rule: Row; onBack: () => void }) {
  const [overview, setOverview] = useState<AnyRecord | null>(null)
  const [checklist, setChecklist] = useState<AnyRecord | null>(null)
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [versionInput, setVersionInput] = useState('')
  const [versionResult, setVersionResult] = useState<AnyRecord[] | null>(null)

  const load = useCallback(async () => {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${rule.id}/discretion`)
      if (!response.ok) {
        throw new Error('频控窗口裁量总览读取失败')
      }
      const payload = await response.json()
      setOverview(payload)
      const list: AnyRecord[] = payload.核对表 ?? []
      setChecklist((prev) => {
        if (prev && list.some((item) => item.核对编号 === prev.核对编号)) {
          return prev
        }
        return list.length ? list[list.length - 1] : null
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '频控窗口裁量总览读取失败')
    }
  }, [rule.id])

  useEffect(() => {
    void load()
  }, [load])

  async function refresh(changeCode: string) {
    setMessage('')
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${rule.id}/discretion/refresh`, {
        method: 'POST',
        body: JSON.stringify({ values: { 记录编号: changeCode } }),
      })
      const payload = await response.json()
      if (!payload.ok) {
        setErrorMessage(payload.message ?? '裁量刷新失败')
        return
      }
      setMessage(payload.message ?? '裁量刷新完成')
      setChecklist(payload.entry ?? null)
      await load()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '裁量刷新失败')
    }
  }

  async function queryVersion() {
    setMessage('')
    setErrorMessage('')
    const version = Number(versionInput)
    if (!Number.isInteger(version) || version <= 0) {
      setErrorMessage('请输入正整数数据版本号')
      return
    }
    try {
      const response = await request(`${ENDPOINT}/${rule.id}/discretion/versions/${version}`)
      if (!response.ok) {
        throw new Error('按数据版本回查失败')
      }
      const payload = await response.json()
      const items: AnyRecord[] = payload.items ?? []
      setVersionResult(items)
      if (items.length > 0) {
        setChecklist(items[items.length - 1])
        setMessage(`数据版本 v${version} 回查到 ${items.length} 份核对表`)
      } else {
        setMessage(`数据版本 v${version} 没有登记的核对表`)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '按数据版本回查失败')
    }
  }

  const changes: AnyRecord[] = overview?.变化记录 ?? []
  const batches: AnyRecord[] = overview?.批次 ?? []
  const checklists: AnyRecord[] = overview?.核对表 ?? []

  return (
    <section className="page" data-module="realtime" data-verify="18e5b997">
      <header className="page-head">
        <div>
          <h2>频控窗口裁量 · {String(rule.规则编号 ?? '')}</h2>
          <p className="page-desc">
            按进出人群生成窗口裁量表：只替换真正进入或离开目标人群的用户，保留其他用户的冷却截止时间。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" data-verify="18d74afe" onClick={onBack}>
            返回列表
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">规则状态</span>
          <strong className="stat-value">{overview?.规则状态 ?? '—'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">冷却时间秒</span>
          <strong className="stat-value">{overview?.冷却时间秒 ?? '—'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">推送批次</span>
          <strong className="stat-value">{batches.length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">已登记核对表</span>
          <strong className="stat-value">{checklists.length}</strong>
        </article>
      </div>

      <section className="detail-panel" data-verify="1882707e">
        <h3 className="section-title">目标人群变化记录（效率改进）</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>记录编号</th>
              <th>分流批次</th>
              <th>基准快照</th>
              <th>目标快照</th>
              <th>受影响记录</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((change) => (
              <tr key={String(change.记录编号)}>
                <td>{change.记录编号}</td>
                <td>{change.分流批次}</td>
                <td>{change.旧快照版本}</td>
                <td>{change.新快照版本}</td>
                <td>{(change.受影响记录 ?? []).length} 条</td>
                <td><span className={`tag ${change.status === '已处理' ? 'ok' : ''}`}>{change.status}</span></td>
                <td>
                  <button className="link" type="button" onClick={() => void refresh(String(change.记录编号))}>
                    生成窗口裁量表
                  </button>
                </td>
              </tr>
            ))}
            {changes.length === 0 && (
              <tr><td className="empty-state" colSpan={7}>暂无目标人群变化记录</td></tr>
            )}
          </tbody>
        </table>
        {message && <p className="message-text">{message}</p>}
        {errorMessage && <p className="error-text">{errorMessage}</p>}
      </section>

      <section className="detail-panel">
        <h3 className="section-title">推送批次现状</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>批次号</th>
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
              <tr><td className="empty-state" colSpan={6}>暂无推送批次</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="detail-panel" data-verify="1823b293">
        <h3 className="section-title">频控窗口裁量明细表</h3>
        {checklist ? (
          <>
            <div className="detail-grid">
              <div className="meta-item">核对编号<strong>{checklist.核对编号}</strong></div>
              <div className="meta-item">分流批次<strong>{checklist.分流批次}</strong></div>
              <div className="meta-item">数据版本<strong>v{checklist.数据版本}</strong></div>
              <div className="meta-item">快照版本<strong>{checklist.快照版本}</strong></div>
              <div className="meta-item">结算状态<strong>{checklist.结算状态}</strong></div>
              <div className="meta-item">待发送人数<strong>{checklist.待发送人数}</strong></div>
            </div>

            <h4 className="section-title">进出人群记录</h4>
            <table className="data-table">
              <thead>
                <tr><th>用户ID</th><th>方向</th><th>触发事件</th><th>原状态</th><th>原冷却截止时间</th></tr>
              </thead>
              <tbody>
                {(checklist.进出人群记录 ?? []).map((record: AnyRecord, index: number) => (
                  <tr key={`${record.用户ID}-${index}`}>
                    <td>{record.用户ID}</td>
                    <td><span className={`tag ${record.方向 === '进入' ? 'ok' : 'warn'}`}>{record.方向}</span></td>
                    <td>{record.触发事件 ?? '—'}</td>
                    <td>{record.原状态 ?? '—'}</td>
                    <td>{record.原冷却截止时间 ?? '—'}</td>
                  </tr>
                ))}
                {(checklist.进出人群记录 ?? []).length === 0 && (
                  <tr><td className="empty-state" colSpan={5}>本次裁量没有进出人群</td></tr>
                )}
              </tbody>
            </table>

            <h4 className="section-title">已完成动作（分别记录，刷新不改写）</h4>
            <table className="data-table">
              <thead>
                <tr><th>用户ID</th><th>动作</th><th>触发事件</th><th>时间</th><th>冷却截止时间</th></tr>
              </thead>
              <tbody>
                {(checklist.已完成动作 ?? []).map((action: AnyRecord, index: number) => (
                  <tr key={`${action.用户ID}-${index}`}>
                    <td>{action.用户ID}</td>
                    <td>{action.动作}</td>
                    <td>{action.触发事件 ?? '—'}</td>
                    <td>{action.时间 ?? '—'}</td>
                    <td>{action.冷却截止时间 ?? '—'}</td>
                  </tr>
                ))}
                {(checklist.已完成动作 ?? []).length === 0 && (
                  <tr><td className="empty-state" colSpan={5}>暂无已完成动作</td></tr>
                )}
              </tbody>
            </table>

            <h4 className="section-title">频控后的推送名单（保留用户与新入用户分别按截止时间追溯）</h4>
            <table className="data-table">
              <thead>
                <tr><th>用户ID</th><th>状态</th><th>触发事件</th><th>冷却截止时间</th><th>追溯口径</th></tr>
              </thead>
              <tbody>
                {(checklist.推送名单 ?? []).map((user: AnyRecord) => (
                  <tr key={String(user.用户ID)}>
                    <td>{user.用户ID}</td>
                    <td>{user.状态}</td>
                    <td>{user.触发事件 ?? '—'}</td>
                    <td>{user.冷却截止时间 ?? '—'}</td>
                    <td><span className="tag">{user.追溯口径}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="empty-state">尚未生成窗口裁量表，请先在上方选择目标人群变化记录</p>
        )}
      </section>

      <section className="detail-panel">
        <h3 className="section-title">按数据版本回查</h3>
        <div className="filter-bar">
          <label className="filter-item">
            <span>数据版本</span>
            <input
              value={versionInput}
              placeholder="如 2"
              onChange={(event) => setVersionInput(event.target.value)}
            />
          </label>
          <button className="btn" type="button" onClick={() => void queryVersion()}>回查</button>
        </div>
        {versionResult && (
          <div className="version-result">
            {versionResult.length === 0 && <span className="empty-state">该版本没有核对表记录</span>}
            {versionResult.map((item) => (
              <button
                key={String(item.核对编号)}
                className="link"
                type="button"
                onClick={() => setChecklist(item)}
              >
                {item.核对编号}（{item.分流批次} · v{item.数据版本} · {item.结算状态}）
              </button>
            ))}
          </div>
        )}
      </section>
    </section>
  )
}
