/**
 * 五步流程上下文：跨页记住 decisionId 与派生资源，供顶栏 Step 切换。
 * 路由主 ID 始终是 decisionId（dec_*）；ontology/simulation/report 仅作派生缓存。
 */
import { reactive } from 'vue'
import { taskRoute } from '../utils/taskRoute'

const STORAGE_KEY = 'adc_workflow_ctx'

function readStorage() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

function migrateLegacy(raw) {
  // 旧字段：projectId/simulationId/reportId 常装 dec_* 或混用
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
    maxReached: raw.maxReached || 1,
    updatedAt: raw.updatedAt || 0,
    // 兼容读：若旧 simulationId 是 dec_，已提升到 decisionId
  }
}

const state = reactive({
  decisionId: '',
  ontologyId: '',
  simulationId: '',
  reportId: '',
  currentStep: 1,
  maxReached: 1,
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
      maxReached: state.maxReached || 1,
      updatedAt: state.updatedAt,
    }),
  )
}

export function getWorkflowContext() {
  return state
}

export function patchWorkflowContext(partial) {
  Object.assign(state, partial, { updatedAt: Date.now() })
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
    // 切换到另一个任务：清空派生缓存
    state.ontologyId = ids.ontologyId || ids.projectId || ''
    state.simulationId =
      ids.simulationId && String(ids.simulationId).startsWith('sim_')
        ? ids.simulationId
        : ''
    state.reportId =
      ids.reportId && String(ids.reportId).startsWith('report_') ? ids.reportId : ''
    state.maxReached = stepNum
  } else {
    state.maxReached = Math.max(Number(state.maxReached || 1), stepNum)
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

/** 已到达过且具备跳转所需 ID（五步均只需 decisionId） */
export function canReachStep(step, ctx = state) {
  const s = Number(step)
  const max = Number(ctx.maxReached || 1)
  if (s > max) return false
  return Boolean(ctx.decisionId) && String(ctx.decisionId) !== 'new'
}

export function routeForStep(step, ctx = state) {
  if (!ctx.decisionId || String(ctx.decisionId) === 'new') return null
  return taskRoute(step, ctx.decisionId)
}
