/**
 * 模拟执行面 API
 * 路由参数多为 decisionId；内部解析为首个/指定 sim_id 后调用 /api/simulation/*
 */
import service, { requestWithRetry } from './index'
import { listOntologies, getOntology, snapshotOntology } from './ontology'
import {
  createDecision,
  getDecision,
  getDecisionStatus,
  listDecisions,
} from './decision'

const simIdCache = new Map()

/** 默认单方案（N=1） */
const defaultScenarios = (title) => [
  {
    name: title || '默认方案',
    kind: 'default',
    color: '#3498db',
    content: title || '',
    poster_hint: 'official',
    initial_posts: title
      ? [{ content: title, poster_hint: 'official' }]
      : [],
  },
]

function pickId(idOrObj) {
  if (!idOrObj) return null
  if (typeof idOrObj === 'string') return idOrObj
  return (
    idOrObj.sim_id ||
    idOrObj.simulation_id ||
    idOrObj.decision_id ||
    null
  )
}

/**
 * 将 decisionId / simId 解析为 { decisionId, simId }
 * - sim_* → 直接当 simId
 * - dec_* → 查决策拿首个 sim_id（可用 run.sim_id 覆盖）
 */
export async function resolveSimContext(idOrObj, preferredSimId = null) {
  const raw = pickId(idOrObj)
  if (!raw) throw new Error('缺少 simulation_id / decision_id')

  if (preferredSimId || (typeof idOrObj === 'object' && idOrObj?.sim_id)) {
    const simId = preferredSimId || idOrObj.sim_id
    const decisionId = raw.startsWith('dec_') ? raw : idOrObj?.decision_id || null
    if (decisionId) simIdCache.set(decisionId, simId)
    return { decisionId, simId }
  }

  if (raw.startsWith('sim_')) {
    return { decisionId: null, simId: raw }
  }

  if (simIdCache.has(raw)) {
    return { decisionId: raw, simId: simIdCache.get(raw) }
  }

  const res = await getDecision(raw)
  const detail = res.data || {}
  const runs =
    detail.runs ||
    (detail.scenarios || []).flatMap((s) => s.runs || []) ||
    (detail.matrix || []).flatMap((m) => m.runs || [])
  const simId =
    detail.sim_id ||
    detail.simulation_id ||
    runs.find((r) => r.sim_id)?.sim_id ||
    null
  if (!simId) {
    throw new Error(
      '该决策没有关联的 simulation（可能是终局架构前的旧数据）。请从本体重新「进入环境搭建」创建。',
    )
  }
  simIdCache.set(raw, simId)
  return { decisionId: raw, simId, detail }
}

/** Step1 → 创建默认 N=1 决策，路由仍用 decisionId */
export const createSimulation = async (data = {}) => {
  const ontologyId = data.project_id || data.ontology_id
  if (!ontologyId) throw new Error('缺少 ontology_id / project_id')

  try {
    await snapshotOntology(ontologyId)
  } catch (_) {
    /* 已有版本时可能失败，忽略 */
  }

  const ont = await getOntology(ontologyId).catch(() => null)
  const title =
    data.title ||
    ont?.data?.simulation_requirement?.slice(0, 40)?.trim() ||
    ont?.data?.name?.slice(0, 40) ||
    `推演 ${ontologyId.slice(0, 8)}`

  const scenarios = (data.scenarios || defaultScenarios(title)).map((s) => ({
    name: s.name,
    kind: s.kind || 'custom',
    color: s.color,
    hypothesis: s.content || s.hypothesis || '',
    preferred_poster_keywords: String(s.poster_hint || '')
      .split(/[,，]/)
      .map((x) => x.trim())
      .filter(Boolean),
    initial_posts:
      s.initial_posts || (s.content ? [{ content: s.content, poster_hint: s.poster_hint || 'official' }] : []),
    content: s.content,
    poster_hint: s.poster_hint,
  }))

  const res = await createDecision({
    ontology_id: ontologyId,
    version_id: data.version_id || null,
    title,
    scenarios,
    sample_count: Number(data.sample_count ?? 1),
    max_rounds: Number(data.max_rounds || 10),
  })

  const payload = res.data || {}
  const decision = payload.decision || payload
  const decisionId = decision?.id
  if (!decisionId) throw new Error(res.error || '创建决策失败')

  const simId =
    payload.sim_id ||
    payload.simulation_id ||
    (payload.runs || []).find((r) => r.sim_id)?.sim_id ||
    null
  if (simId) simIdCache.set(decisionId, simId)

  return {
    success: true,
    data: {
      ...decision,
      // 路由参数继续用 decisionId，兼容现有五步页面
      simulation_id: decisionId,
      decision_id: decisionId,
      sim_id: simId,
      project_id: ontologyId,
      ontology_id: ontologyId,
      graph_id: ont?.data?.graph_id,
      status: decision?.status || 'created',
      scenario_count: scenarios.length,
      sample_count: Number(data.sample_count ?? 1),
    },
  }
}

export const prepareSimulation = async (data = {}) => {
  const { simId, decisionId, detail } = await resolveSimContext(data)
  const scenarioCount =
    detail?.scenarios?.length ||
    detail?.matrix?.length ||
    data.scenario_count ||
    1

  // N>1：走决策共享世界 prepare
  if (scenarioCount > 1 && decisionId) {
    const { prepareDecision } = await import('./decision')
    const res = await prepareDecision(decisionId, data)
    return {
      success: true,
      data: {
        task_id: decisionId,
        simulation_id: simId,
        decision_id: decisionId,
        status: 'completed',
        progress: 100,
        ...(res.data || {}),
      },
    }
  }

  return requestWithRetry(
    () =>
      service.post('/api/simulation/prepare', {
        simulation_id: simId,
        simulation_requirement: data.simulation_requirement,
        document_text: data.document_text,
        entity_types: data.entity_types,
        use_llm_for_profiles: data.use_llm_for_profiles ?? true,
        parallel_profile_count: data.parallel_profile_count ?? 5,
        force_regenerate: data.force_regenerate ?? false,
      }),
    3,
    1000,
  )
}

export const getPrepareStatus = async (data) => {
  const payload = typeof data === 'string' ? { simulation_id: data } : data || {}
  try {
    const { simId } = await resolveSimContext(payload)
    return service.post('/api/simulation/prepare/status', {
      ...payload,
      simulation_id: simId,
      task_id: payload.task_id,
    })
  } catch (e) {
    return {
      success: false,
      error: e.message,
      data: { status: 'failed', progress: 0 },
    }
  }
}

export const getSimulation = async (id) => {
  const raw = pickId(id) || id
  // 决策详情（含 matrix / scenarios）
  if (raw && String(raw).startsWith('dec_')) {
    const res = await getDecision(raw)
    const detail = res.data || {}
    const decision = detail.decision || detail
    const ontologyId = decision.ontology_id
    let ontology = null
    if (ontologyId) {
      try {
        ontology = (await getOntology(ontologyId)).data
      } catch (_) {
        /* ignore */
      }
    }
    const simId =
      detail.sim_id ||
      (detail.runs || []).find((r) => r.sim_id)?.sim_id ||
      simIdCache.get(raw)
    if (simId) simIdCache.set(raw, simId)
    return {
      success: true,
      data: {
        ...decision,
        ...detail,
        simulation_id: raw,
        decision_id: raw,
        sim_id: simId,
        project_id: ontologyId,
        ontology_id: ontologyId,
        graph_id: ontology?.graph_id,
        project: ontology
          ? { ...ontology, project_id: ontology.id, ontology: ontology.schema }
          : null,
        status: decision.status,
      },
    }
  }
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}`)
}

export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

export const startSimulation = async (data = {}) => {
  const { simId, decisionId, detail } = await resolveSimContext(data)
  const scenarioCount =
    detail?.scenarios?.length || detail?.matrix?.length || 1

  // N>1：编排器批量启动
  if (scenarioCount > 1 && decisionId) {
    const { startDecision } = await import('./decision')
    return startDecision(decisionId, { background: true, ...data })
  }

  return requestWithRetry(
    () =>
      service.post('/api/simulation/start', {
        ...data,
        simulation_id: simId,
      }),
    3,
    1000,
  )
}

export const stopSimulation = async (data = {}) => {
  const { simId } = await resolveSimContext(data)
  return service.post('/api/simulation/stop', { ...data, simulation_id: simId })
}

export const getEnvStatus = async (data = {}) => {
  const { simId } = await resolveSimContext(data)
  return service.post('/api/simulation/env-status', { ...data, simulation_id: simId })
}

export const closeSimulationEnv = async (data = {}) => {
  const { simId } = await resolveSimContext(data)
  return service.post('/api/simulation/close-env', { ...data, simulation_id: simId })
}

export const getRunStatus = async (id) => {
  const raw = pickId(id) || id
  // 决策级：返回矩阵 + 兼容 Step3 单时间线字段
  if (raw && String(raw).startsWith('dec_')) {
    const st = await getDecisionStatus(raw)
    const data = st.data || {}
    const progress = data.progress || { done: 0, total: 0 }
    const status = data.status || data.decision?.status
    const completed = ['completed', 'done', 'success'].includes(status)
    const running = status === 'running'
    const totalRounds = data.decision?.max_rounds || 10
    const pct = progress.total ? progress.done / progress.total : completed ? 1 : 0
    const currentRound = Math.round(pct * totalRounds)

    // 若 N=1，叠加真 sim run-status
    const firstSim =
      data.matrix?.[0]?.runs?.[0]?.sim_id || simIdCache.get(raw)
    let simStatus = null
    if (firstSim) {
      try {
        simStatus = (await service.get(`/api/simulation/${firstSim}/run-status`)).data
      } catch (_) {
        /* ignore */
      }
    }

    return {
      success: true,
      data: {
        ...data,
        ...(simStatus || {}),
        status,
        total_rounds: simStatus?.total_rounds || totalRounds,
        twitter_running: simStatus?.twitter_running ?? running,
        reddit_running: simStatus?.reddit_running ?? false,
        twitter_completed: simStatus?.twitter_completed ?? completed,
        reddit_completed: simStatus?.reddit_completed ?? completed,
        twitter_current_round: simStatus?.twitter_current_round ?? currentRound,
        reddit_current_round: simStatus?.reddit_current_round ?? currentRound,
        matrix: data.matrix,
        decision_id: raw,
        sim_id: firstSim,
      },
    }
  }
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/run-status`)
}

export const getRunStatusDetail = async (id) => {
  const raw = pickId(id) || id
  if (raw && String(raw).startsWith('dec_')) {
    const st = await getRunStatus(raw)
    const matrix = st.data?.matrix || []
    const simIds = matrix
      .flatMap((m) => (m.runs || []).map((r) => r.sim_id || r.run_id))
      .filter(Boolean)

    const all_actions = []
    await Promise.all(
      simIds.slice(0, 6).map(async (sid) => {
        try {
          const res = await service.get(`/api/simulation/${sid}/actions`, {
            params: { limit: 80 },
          })
          const actions = res.data?.actions || res.data || []
          for (const a of actions) {
            all_actions.push({ ...a, platform: a.platform || 'twitter', sim_id: sid })
          }
        } catch (_) {
          /* ignore */
        }
      }),
    )
    all_actions.sort((a, b) =>
      String(a.timestamp || '').localeCompare(String(b.timestamp || '')),
    )
    return {
      success: true,
      data: {
        ...(st.data || {}),
        all_actions,
        twitter_actions_count: all_actions.filter((a) => a.platform !== 'reddit').length,
        reddit_actions_count: all_actions.filter((a) => a.platform === 'reddit').length,
      },
    }
  }
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/run-status/detail`)
}

export const getSimulationPosts = async (id, platform = 'reddit', limit = 50, offset = 0) => {
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/posts`, {
    params: { platform, limit, offset },
  })
}

export const getSimulationProfiles = async (id, platform = 'reddit') => {
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/profiles`, { params: { platform } })
}

export const getSimulationProfilesRealtime = async (id, platform = 'reddit') => {
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/profiles/realtime`, {
    params: { platform },
  })
}

export const getSimulationConfig = async (id) => {
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/config`)
}

export const getSimulationConfigRealtime = async (id) => {
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/config/realtime`)
}

export const interviewAgent = async (data = {}) => {
  const { simId } = await resolveSimContext(data)
  return service.post('/api/simulation/interview', {
    ...data,
    simulation_id: simId,
  })
}

export const interviewAgents = async (data = {}) => {
  const preferred = data.sim_id || data.run_sim_id
  const { simId } = await resolveSimContext(data, preferred)
  return requestWithRetry(
    () =>
      service.post('/api/simulation/interview/batch', {
        ...data,
        simulation_id: simId,
      }),
    3,
    1000,
  )
}

export const getActions = async (id, params = {}) => {
  // 兼容 run_id 或 sim_id
  if (String(id || '').startsWith('run_')) {
    return service.get(`/api/run/${id}/actions`, { params })
  }
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/actions`, { params })
}

const toHistoryFiles = (documents = []) =>
  (documents || [])
    .filter((doc) => doc && (doc.filename || doc.name))
    .map((doc) => ({
      filename: doc.filename || doc.name,
      id: doc.id,
      char_count: doc.char_count,
    }))

/** 历史库：本体 + 决策（N=1 显示为单次推演） */
export const getSimulationHistory = async (limit = 20) => {
  const [ontologies, decisions] = await Promise.all([
    listOntologies().catch(() => ({ data: [] })),
    listDecisions().catch(() => ({ data: [] })),
  ])
  const ontList = ontologies.data || []
  const decList = decisions.data || []

  const docsByOntology = Object.fromEntries(
    ontList.map((o) => [o.id, toHistoryFiles(o.documents)]),
  )

  const fromDecisions = decList.slice(0, limit).map((d) => {
    const n = Number(d.sample_count || 1)
    // 无法直接拿 scenario 数时，用标题启发式；详情页再区分
    return {
      kind: 'decision',
      simulation_id: d.id,
      project_id: d.ontology_id,
      report_id: d.id,
      decision_id: d.id,
      ontology_id: d.ontology_id,
      simulation_requirement: d.title || d.id,
      status: d.status,
      created_at: d.created_at,
      current_round: d.status === 'completed' ? 1 : 0,
      total_rounds: 1,
      sample_count: n,
      files: docsByOntology[d.ontology_id] || [],
    }
  })

  const remain = Math.max(0, limit - fromDecisions.length)
  const fromOntologies = ontList.slice(0, remain).map((o) => ({
    kind: 'ontology',
    simulation_id: o.id,
    project_id: o.id,
    report_id: null,
    ontology_id: o.id,
    simulation_requirement: o.simulation_requirement || o.name || o.id,
    status: o.status,
    created_at: o.created_at,
    current_round: o.status === 'ready' ? 1 : 0,
    total_rounds: 1,
    files: docsByOntology[o.id] || toHistoryFiles(o.documents),
  }))

  return { success: true, data: [...fromDecisions, ...fromOntologies].slice(0, limit) }
}
