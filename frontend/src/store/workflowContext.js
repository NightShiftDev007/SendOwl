/**
 * 五步流程上下文：跨页记住 project / simulation / report，供顶栏 Step 切换。
 */
import { reactive } from 'vue'

const STORAGE_KEY = 'adc_workflow_ctx'

function readStorage() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}') || {}
  } catch {
    return {}
  }
}

const state = reactive({
  projectId: '',
  simulationId: '',
  reportId: '',
  currentStep: 1,
  maxReached: 1,
  updatedAt: 0,
})

Object.assign(state, readStorage())

function persist() {
  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      projectId: state.projectId || '',
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
  const prevProject = state.projectId
  const prevSim = state.simulationId

  if (ids.projectId && prevProject && ids.projectId !== prevProject) {
    state.simulationId = ids.simulationId || ''
    state.reportId = ids.reportId || ''
    state.maxReached = stepNum
  } else if (
    ids.simulationId &&
    prevSim &&
    ids.simulationId !== prevSim &&
    !ids.reportId
  ) {
    state.reportId = ''
    state.maxReached = Math.max(stepNum, 3)
  } else {
    state.maxReached = Math.max(Number(state.maxReached || 1), stepNum)
  }

  if (ids.projectId) state.projectId = ids.projectId
  if (ids.simulationId) state.simulationId = ids.simulationId
  if (ids.reportId) state.reportId = ids.reportId
  state.currentStep = stepNum
  state.updatedAt = Date.now()
  persist()
  return state
}

/** 已到达过且具备跳转所需 ID */
export function canReachStep(step, ctx = state) {
  const s = Number(step)
  const max = Number(ctx.maxReached || 1)
  if (s > max) return false
  if (s === 1) return Boolean(ctx.projectId)
  if (s === 2 || s === 3) return Boolean(ctx.simulationId)
  if (s === 4 || s === 5) return Boolean(ctx.reportId)
  return false
}

export function routeForStep(step, ctx = state) {
  const s = Number(step)
  if (s === 1 && ctx.projectId) {
    return { name: 'Process', params: { projectId: ctx.projectId } }
  }
  if (s === 2 && ctx.simulationId) {
    return { name: 'Simulation', params: { simulationId: ctx.simulationId } }
  }
  if (s === 3 && ctx.simulationId) {
    return {
      name: 'SimulationRun',
      params: { simulationId: ctx.simulationId },
    }
  }
  if (s === 4 && ctx.reportId) {
    return { name: 'Report', params: { reportId: ctx.reportId } }
  }
  if (s === 5 && ctx.reportId) {
    return { name: 'Interaction', params: { reportId: ctx.reportId } }
  }
  return null
}
