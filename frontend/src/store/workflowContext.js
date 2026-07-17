/**
 * 五步流程上下文。
 *
 * - decisionId / ontologyId / simulationId / reportId：派生资源缓存（可写 sessionStorage）
 * - 顶栏可到达阶段：只看后端任务状态（serverMaxReached），不按本机浏览进度记
 */
import { reactive } from 'vue'
import { taskRoute } from '../utils/taskRoute'
import { getDecision } from '../api/decision'
import { getReport, resolveReportId } from '../api/report'
import { getSimulationConfig } from '../api/simulation'

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
function isStrongEventConfig(eventConfig) {
  if (!eventConfig || typeof eventConfig !== 'object') return false
  const posts = (eventConfig.initial_posts || []).filter(
    (p) => p && String(p.content || '').trim(),
  )
  const topics = (eventConfig.hot_topics || []).filter((t) => String(t || '').trim())
  const narrative = String(eventConfig.narrative_direction || '').trim()
  return posts.length >= 2 && topics.length >= 1 && Boolean(narrative)
}

export function inferMaxReachedFromDecisionPayload(data, extra = {}) {
  // 只用原始决策状态；envelope.status 可能把 prepared 映射成 completed，会误解锁
  const dec = data?.decision || {}
  const status = String(dec.status || data?.status || '').toLowerCase()
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
  // 真正开跑过（不含 prepare 后的 ready）
  const anySimStarted = runs.some((r) =>
    ['running', 'failed', 'stopped', 'completed', 'timeout', 'stalled'].includes(
      String(r?.status || '').toLowerCase(),
    ),
  )
  const hasReport = Boolean(extra.hasReport)
  // 默认偏保守：未显式确认 eventReady 时，不得凭 prepared 解锁 Step3
  const eventReady = extra.eventReady === true

  // 重做环境 / 方案刚替换：旧 run、旧报告一律作废，后续步骤全部失效
  if (status === 'preparing' || status === 'prepare_failed') return 2
  if (status === 'created') return hasOntology || hasScenarios ? 2 : 1

  // 有可用报告 → 互动（仍要求至少推演过）
  if (hasReport && (anyCompletedRun || status === 'completed')) return 5
  // 推演整体完成（或至少有完成 run）→ 可进报告
  if (status === 'completed' || (status === 'failed' && anyCompletedRun)) return 4
  // 正在推演 / 已开跑 → Step3
  if (status === 'running' || anyRunning || anySimStarted) return 3
  // 环境已准备：必须初始激活合格才解锁 Step3
  if (status === 'prepared') return eventReady ? 3 : 2
  if (status === 'failed' && !anyCompletedRun) return eventReady ? 3 : 2
  if (hasOntology || hasScenarios) return 2
  return 1
}

/** Step2 检测到弱编排/失败时立刻压顶栏上限（不必等下一次 sync） */
export function capWorkflowMaxReached(maxStep) {
  const cap = Math.max(1, Math.min(5, Number(maxStep) || 1))
  if (state.serverMaxReached == null || Number(state.serverMaxReached) > cap) {
    state.serverMaxReached = cap
    state.updatedAt = Date.now()
  }
  return state
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

      const dec = data.decision || {}
      // 禁止用 envelope 映射状态（prepared→completed 会误解锁）
      const status = String(dec.status || data?.status || '').toLowerCase()
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

      // 默认 false：只有读到强 event_config 才解锁 Step3
      // gtv_deal 商业模板：轻量 prepare 后即可进 Step3（不依赖社媒编排）
      const template = String(dec.template || data.template || '').toLowerCase()
      let eventReady = false
      if (status === 'prepare_failed' || status === 'preparing') {
        eventReady = false
      } else if (template === 'gtv_deal') {
        eventReady = ['prepared', 'running', 'completed', 'failed'].includes(status)
      } else if (simId) {
        try {
          const cfgRes = await getSimulationConfig(simId)
          const cfg = cfgRes?.data || cfgRes || {}
          eventReady = isStrongEventConfig(cfg.event_config)
        } catch (_) {
          eventReady = false
        }
      }

      // 先按决策状态算基础可达步骤；只有推演已有完成结果（>=4）才探测报告。
      // 否则 getReport 会退回 compare 接口——它对新决策也会即时生成模板报告，
      // 导致 hasReport 误判为 true、顶栏全解锁。
      const baseInferred = inferMaxReachedFromDecisionPayload(data, { eventReady })
      let hasReport = false
      if (baseInferred >= 4) {
        try {
          const rid = await resolveReportId(id)
          if (rid && String(rid).startsWith('report_')) {
            hasReport = true
            state.reportId = rid
          } else {
            // 无独立 report_* 时：对比/叙事正文也算「有报告」，可进互动
            const rep = await getReport(id)
            const d = rep?.data || {}
            const md =
              d.markdown_content ||
              d.report?.markdown ||
              d.markdown ||
              ''
            if (String(md).trim().length > 40) {
              hasReport = true
              if (d.report_id && String(d.report_id).startsWith('report_')) {
                state.reportId = d.report_id
              }
            }
          }
        } catch (_) {
          /* ignore */
        }
      }

      const inferred = inferMaxReachedFromDecisionPayload(data, { hasReport, eventReady })

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
