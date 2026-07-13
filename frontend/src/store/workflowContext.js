/**
 * 五步流程上下文。
 *
 * - decisionId / ontologyId / simulationId / reportId：派生资源缓存（可写 sessionStorage）
 * - 顶栏可到达阶段：只看后端任务状态（serverMaxReached），不按本机浏览进度记
 */
import { reactive } from 'vue'
import { taskRoute } from '../utils/taskRoute'
import { getDecision } from '../api/decision'
import { resolveReportId } from '../api/report'

const STORAGE_KEY = 'adc_workflow_ctx'

function readStorage() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

function migrateLegacy(raw) {
  const decisionId =
    raw.decisionId ||
    (String(raw.simulationId || '').startsWith('dec_') ? raw.simulationId : '') ||
    (String(raw.reportId || '').startsWith('dec_') ? raw.reportId : '') ||
    ''
  return {
    decisionId,
    ontologyId: raw.ontologyId || (String(raw.projectId || '').startsWith('ont_') ? raw.projectId : '') || '',
    simulationId: raw.simulationId && String(raw.simulationId).startsWith('sim_') ? raw.simulationId : '',
    reportId: raw.reportId && String(raw.reportId).startsWith('report_') ? raw.reportId : '',
    currentStep: raw.currentStep || 1,
    updatedAt: raw.updatedAt || 0,
  }
}

const state = reactive({
  decisionId: '',
  ontologyId: '',
  simulationId: '',
  reportId: '',
  currentStep: 1,
  /** 后端推断的可到达最大步骤；null 表示尚未拉取 */
  serverMaxReached: null,
  serverStatus: '',
  serverSyncedAt: 0,
  updatedAt: 0,
})

Object.assign(state, migrateLegacy(readStorage()))

function persist() {
  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      decisionId: state.decisionId || '',
      ontologyId: state.ontologyId || '',
      simulationId: state.simulationId || '',
      reportId: state.reportId || '',
      currentStep: state.currentStep || 1,
      updatedAt: state.updatedAt,
    }),
  )
}

export function getWorkflowContext() {
  return state
}

export function patchWorkflowContext(partial) {
  const next = { ...partial }
  // 进度不得由调用方本地写入
  delete next.maxReached
  delete next.serverMaxReached
  Object.assign(state, next, { updatedAt: Date.now() })
  persist()
  return state
}

export function touchWorkflowStep(step, ids = {}) {
  const stepNum = Number(step) || 1
  const nextDecision =
    ids.decisionId ||
    (String(ids.simulationId || '').startsWith('dec_') ? ids.simulationId : null) ||
    (String(ids.reportId || '').startsWith('dec_') ? ids.reportId : null)

  if (nextDecision && state.decisionId && nextDecision !== state.decisionId) {
    state.ontologyId = ids.ontologyId || ids.projectId || ''
    state.simulationId =
      ids.simulationId && String(ids.simulationId).startsWith('sim_')
        ? ids.simulationId
        : ''
    state.reportId =
      ids.reportId && String(ids.reportId).startsWith('report_') ? ids.reportId : ''
    state.serverMaxReached = null
    state.serverStatus = ''
    state.serverSyncedAt = 0
  }

  if (nextDecision) state.decisionId = nextDecision
  if (ids.ontologyId) state.ontologyId = ids.ontologyId
  else if (ids.projectId && String(ids.projectId).startsWith('ont_')) {
    state.ontologyId = ids.projectId
  }
  if (ids.simulationId && String(ids.simulationId).startsWith('sim_')) {
    state.simulationId = ids.simulationId
  }
  if (ids.reportId && String(ids.reportId).startsWith('report_')) {
    state.reportId = ids.reportId
  }

  state.currentStep = stepNum
  state.updatedAt = Date.now()
  persist()
  return state
}

/**
 * 根据决策详情推断顶栏应解锁到第几步。
 * 对齐后端真实状态：created / preparing / prepare_failed / prepared / running / failed / completed
 * 1 本体 · 2 环境 · 3 模拟 · 4 报告 · 5 互动
 *
 * @param {object} data getDecision 返回的 data
 * @param {{ hasReport?: boolean }} [extra]
 */
export function inferMaxReachedFromDecisionPayload(data, extra = {}) {
  const dec = data?.decision || data || {}
  const status = String(
    dec.status || data?.envelope?.status || data?.envelope?.raw_status || '',
  ).toLowerCase()
  const matrix = data?.matrix || []
  const runs = matrix.flatMap((s) => s.runs || [])
  const hasOntology = Boolean(dec.ontology_id)
  const hasScenarios = matrix.length > 0 || (data?.scenarios || []).length > 0
  const anyRunning = runs.some((r) => String(r?.status || '').toLowerCase() === 'running')
  const anyCompletedRun = runs.some(
    (r) =>
      String(r?.status || '').toLowerCase() === 'completed' ||
      r?.has_metrics === true,
  )
  const hasReport = Boolean(extra.hasReport)

  // 有可用报告 → 互动
  if (hasReport) return 5
  // 推演整体完成（或至少有完成 run）→ 可进报告；勿因空壳 sim_id 提前解锁
  if (status === 'completed' || (status === 'failed' && anyCompletedRun)) return 4
  if (status === 'running' || anyRunning) return 3
  if (status === 'prepared') return 3
  if (status === 'preparing' || status === 'prepare_failed') return 2
  if (status === 'failed' && !anyCompletedRun) return 3
  if (hasOntology || hasScenarios || status === 'created') return 2
  return 1
}

/** 顶栏是否可点：以服务端进度为准；当前页始终可点，避免拉取中闪锁 */
export function canReachStep(step, ctx = state) {
  const s = Number(step)
  if (!ctx.decisionId || String(ctx.decisionId) === 'new') return false
  if (s === Number(ctx.currentStep)) return true
  const max =
    ctx.serverMaxReached != null
      ? Number(ctx.serverMaxReached)
      : Number(ctx.currentStep || 1)
  return s <= max
}

/** @deprecated 兼容旧调用；实际等于 serverMaxReached ?? currentStep */
export function getEffectiveMaxReached(ctx = state) {
  if (ctx.serverMaxReached != null) return Number(ctx.serverMaxReached)
  return Number(ctx.currentStep || 1)
}

export function routeForStep(step, ctx = state) {
  if (!ctx.decisionId || String(ctx.decisionId) === 'new') return null
  return taskRoute(step, ctx.decisionId)
}

const _syncInflight = new Map()

/**
 * 用任务 ID 拉后端状态，写入 serverMaxReached（进度唯一来源）。
 */
export async function syncWorkflowFromServer(decisionId) {
  const id = String(decisionId || '').trim()
  if (!id.startsWith('dec_')) return state
  if (_syncInflight.has(id)) return _syncInflight.get(id)

  const job = (async () => {
    try {
      const res = await getDecision(id)
      const data = res?.data || res
      if (!data) return state

      let hasReport = false
      try {
        const rid = await resolveReportId(id)
        hasReport = Boolean(rid && String(rid).startsWith('report_'))
        if (hasReport) state.reportId = rid
      } catch (_) {
        /* ignore */
      }

      const inferred = inferMaxReachedFromDecisionPayload(data, { hasReport })
      const dec = data.decision || {}
      const status = String(dec.status || data?.envelope?.status || '').toLowerCase()
      // 仅取「已完成」run 的 sim，避免空壳 sim 误导下游
      const simId =
        (data.matrix || [])
          .flatMap((s) => s.runs || [])
          .filter(
            (r) =>
              r?.sim_id &&
              (String(r.status || '').toLowerCase() === 'completed' || r.has_metrics),
          )
          .map((r) => r.sim_id)
          .find((x) => String(x).startsWith('sim_')) ||
        (data.matrix || [])
          .flatMap((s) => s.runs || [])
          .map((r) => r.sim_id)
          .find((x) => x && String(x).startsWith('sim_')) ||
        ''

      if (state.decisionId && state.decisionId !== id) {
        return state
      }

      state.decisionId = id
      state.serverMaxReached = inferred
      state.serverStatus = status
      state.serverSyncedAt = Date.now()
      if (dec.ontology_id) state.ontologyId = dec.ontology_id
      if (simId) state.simulationId = simId
      state.updatedAt = Date.now()
      persist()
      return state
    } catch (e) {
      console.warn('[workflow] sync from server failed', id, e)
      return state
    } finally {
      _syncInflight.delete(id)
    }
  })()

  _syncInflight.set(id, job)
  return job
}
