/**
 * 统一任务路由：/tasks/:decisionId/:stage
 * decisionId 始终为业务任务 ID（dec_*），派生资源另解析。
 */

export const TASK_STAGES = {
  1: 'graph',
  2: 'environment',
  3: 'simulation',
  4: 'report',
  5: 'interaction',
}

export const STAGE_TO_STEP = {
  graph: 1,
  environment: 2,
  simulation: 3,
  report: 4,
  interaction: 5,
}

export const TASK_ROUTE_NAMES = {
  1: 'TaskGraph',
  2: 'TaskEnvironment',
  3: 'TaskSimulation',
  4: 'TaskReport',
  5: 'TaskInteraction',
}

export function isDecisionId(id) {
  return Boolean(id) && String(id).startsWith('dec_')
}

export function isOntologyId(id) {
  return Boolean(id) && String(id).startsWith('ont_')
}

export function isSimulationId(id) {
  return Boolean(id) && String(id).startsWith('sim_')
}

export function isReportId(id) {
  return Boolean(id) && String(id).startsWith('report_')
}

/** 生成五步任务路由对象 */
export function taskRoute(stepOrStage, decisionId, query) {
  const step =
    typeof stepOrStage === 'number'
      ? stepOrStage
      : STAGE_TO_STEP[stepOrStage] || 1
  const name = TASK_ROUTE_NAMES[step] || TASK_ROUTE_NAMES[1]
  const route = {
    name,
    params: { decisionId: String(decisionId || '') },
  }
  if (query && Object.keys(query).length) route.query = query
  return route
}

/**
 * 将任意历史 ID 解析为 decisionId。
 * - dec_* → 原样
 * - 'new' → 'new'（瞬态新建入口）
 * - ont_* → 同本体活跃决策
 * - sim_* → 所属决策
 * - report_* → 经 simulation 反查所属决策
 * 解析失败返回 null。
 */
export async function resolveDecisionId(raw) {
  if (!raw) return null
  const id = String(raw)
  if (id === 'new') return 'new'
  if (isDecisionId(id)) return id

  const { listDecisions, getDecision } = await import('../api/decision')

  if (isOntologyId(id)) {
    try {
      const listed = await listDecisions()
      const raw = listed?.data
      const arr = Array.isArray(raw)
        ? raw
        : Array.isArray(raw?.decisions)
          ? raw.decisions
          : Array.isArray(listed?.decisions)
            ? listed.decisions
            : []
      const found = arr.find((d) => d.ontology_id === id || d.project_id === id)
      return found?.id || null
    } catch {
      return null
    }
  }

  if (isSimulationId(id)) {
    try {
      const listed = await listDecisions()
      const raw = listed?.data
      const arr = Array.isArray(raw)
        ? raw
        : Array.isArray(raw?.decisions)
          ? raw.decisions
          : Array.isArray(listed?.decisions)
            ? listed.decisions
            : []
      for (const d of arr) {
        if (!d?.id) continue
        const detail = await getDecision(d.id).catch(() => null)
        const payload = detail?.data || {}
        const runs = [
          ...(payload.runs || []),
          ...((payload.scenarios || []).flatMap((s) => s.runs || [])),
        ]
        if (payload.sim_id === id || runs.some((r) => r?.sim_id === id)) {
          return d.id
        }
      }
    } catch {
      /* ignore */
    }
    return null
  }

  if (isReportId(id)) {
    try {
      const service = (await import('../api/index')).default
      const res = await service.get(`/api/report/${id}`)
      const data = res?.data || res
      const simId = data?.simulation_id || data?.sim_id
      const decisionHint = data?.decision_id
      if (isDecisionId(decisionHint)) return decisionHint
      if (simId) return resolveDecisionId(simId)
    } catch {
      /* ignore */
    }
    return null
  }

  // 未知前缀：若本身像决策则交给调用方；否则尝试列表命中
  return null
}
