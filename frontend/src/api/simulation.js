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
  ensureDecisionSims,
} from './decision'

const simIdCache = new Map()
/** decisionId -> { simId, cachedAt }；命中后默认不再回源 getDecision */
const SIM_ID_CACHE_TTL_MS = 30_000

/** 换方案 / 重建 sims 后清缓存，避免订到旧 sim */
export function clearSimIdCache(decisionId = null) {
  if (decisionId) {
    simIdCache.delete(String(decisionId))
    return
  }
  simIdCache.clear()
}

function cacheGet(decisionId) {
  const hit = simIdCache.get(String(decisionId))
  if (!hit) return null
  if (typeof hit === 'string') {
    // 兼容旧缓存形态
    return { simId: hit, cachedAt: 0 }
  }
  return hit
}

function cacheSet(decisionId, simId) {
  simIdCache.set(String(decisionId), { simId, cachedAt: Date.now() })
}

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
    if (decisionId) cacheSet(decisionId, simId)
    return { decisionId, simId }
  }

  if (raw.startsWith('sim_')) {
    return { decisionId: null, simId: raw }
  }

  const cached = cacheGet(raw)
  if (cached?.simId) {
    const age = Date.now() - (cached.cachedAt || 0)
    // TTL 内直接返回，不再每拍回源 getDecision（消除双 dec_* 请求）
    if (age < SIM_ID_CACHE_TTL_MS) {
      return { decisionId: raw, simId: cached.simId }
    }
    // TTL 过期：回源刷新；失败则沿用缓存
    try {
      const res = await getDecision(raw)
      const detail = res.data || {}
      const runs =
        detail.runs ||
        (detail.scenarios || []).flatMap((s) => s.runs || []) ||
        (detail.matrix || []).flatMap((m) => m.runs || [])
      const fresh =
        detail.sim_id ||
        detail.simulation_id ||
        runs.find((r) => r.sim_id)?.sim_id ||
        null
      if (fresh) {
        cacheSet(raw, fresh)
        return { decisionId: raw, simId: fresh, detail }
      }
      // 方案已替换但 sim 尚未就绪：清掉失效缓存，走下方补建逻辑
      simIdCache.delete(raw)
    } catch (_) {
      return { decisionId: raw, simId: cached.simId }
    }
  }

  const res = await getDecision(raw)
  const detail = res.data || {}
  const runs =
    detail.runs ||
    (detail.scenarios || []).flatMap((s) => s.runs || []) ||
    (detail.matrix || []).flatMap((m) => m.runs || [])
  let simId =
    detail.sim_id ||
    detail.simulation_id ||
    runs.find((r) => r.sim_id)?.sim_id ||
    null

  // 建图前创建的任务可能尚无 sim：尝试补建空壳
  if (!simId && raw.startsWith('dec_')) {
    try {
      const ensured = await ensureDecisionSims(raw)
      const ed = ensured?.data || {}
      const eruns =
        ed.runs ||
        (ed.scenarios || []).flatMap((s) => s.runs || []) ||
        (ed.matrix || []).flatMap((m) => m.runs || [])
      simId =
        ed.sim_id ||
        ed.simulation_id ||
        eruns.find((r) => r.sim_id)?.sim_id ||
        null
      if (simId) {
        cacheSet(raw, simId)
        return { decisionId: raw, simId, detail: { ...detail, ...ed } }
      }
    } catch (_) {
      /* 图谱未就绪时会失败，交给调用方 */
    }
  }

  if (!simId) {
    throw new Error(
      '该决策尚未关联 simulation（图谱可能仍在构建）。请等建图完成后再进入环境搭建。',
    )
  }
  cacheSet(raw, simId)
  return { decisionId: raw, simId, detail }
}

/** Step1 → 创建默认 N=1 决策，路由仍用 decisionId。
 * 未显式传 scenarios 时复用同本体活跃决策，避免历史回放/反复进入重复建卡。
 * Step2 换方案请走 replaceDecisionScenarios（原地更新），不要再 createSimulation。
 */
export const createSimulation = async (data = {}) => {
  const ontologyId = data.project_id || data.ontology_id
  if (!ontologyId) throw new Error('缺少 ontology_id / project_id')

  const hasExplicitScenarios =
    Array.isArray(data.scenarios) && data.scenarios.length > 0

  // 复用：同本体已有活跃决策，且本次未显式传方案
  if (!hasExplicitScenarios) {
    try {
      const listed = await listDecisions()
      const decList = listed?.data || []
      const existing = decList.find((d) => d.ontology_id === ontologyId)
      if (existing?.id) {
        const ont = await getOntology(ontologyId).catch(() => null)
        let detail = await getDecision(existing.id).catch(() => null)
        let payload = detail?.data || {}
        let simId =
          payload.sim_id ||
          (payload.runs || []).find((r) => r.sim_id)?.sim_id ||
          (payload.scenarios || [])
            .flatMap((s) => s.runs || [])
            .find((r) => r.sim_id)?.sim_id ||
          null

        // 建图已完成但任务尚无 sim：补建空壳，保证进入 Step2 可用
        if (!simId && ont?.data?.graph_id) {
          try {
            await snapshotOntology(ontologyId).catch(() => null)
            const ensured = await ensureDecisionSims(existing.id)
            payload = ensured?.data || payload
            simId =
              payload.sim_id ||
              (payload.scenarios || [])
                .flatMap((s) => s.runs || [])
                .find((r) => r.sim_id)?.sim_id ||
              null
          } catch (_) {
            /* prepare 阶段仍会再补 */
          }
        }

        if (simId) simIdCache.set(existing.id, simId)
        return {
          success: true,
          data: {
            ...existing,
            simulation_id: existing.id,
            decision_id: existing.id,
            sim_id: simId,
            project_id: ontologyId,
            ontology_id: ontologyId,
            graph_id: ont?.data?.graph_id,
            status: existing.status || 'created',
            scenario_count: (payload.scenarios || []).length || 1,
            sample_count: Number(existing.sample_count ?? 1),
            reused: true,
          },
        }
      }
    } catch (_) {
      /* 列表失败则继续创建 */
    }
  }

  try {
    await snapshotOntology(ontologyId)
  } catch (_) {
    /* 建图前尚无图谱/已有版本时可能失败，忽略；后端允许空 version_id */
  }

  const ont = await getOntology(ontologyId).catch(() => null)
  const title =
    data.title ||
    ont?.data?.simulation_requirement?.slice(0, 40)?.trim() ||
    ont?.data?.name?.slice(0, 40) ||
    `推演 ${ontologyId.slice(0, 8)}`

  const scenarios = (hasExplicitScenarios ? data.scenarios : defaultScenarios(title)).map(
    (s) => ({
      name: s.name,
      kind: s.kind || 'custom',
      color: s.color,
      hypothesis: s.content || s.hypothesis || '',
      preferred_poster_keywords: String(s.poster_hint || '')
        .split(/[,，]/)
        .map((x) => x.trim())
        .filter(Boolean),
      initial_posts:
        s.initial_posts ||
        (s.content ? [{ content: s.content, poster_hint: s.poster_hint || 'official' }] : []),
      content: s.content,
      poster_hint: s.poster_hint,
    }),
  )

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

/** 真实异步任务 ID（排除误把 dec_/sim_ 当 task_id） */
export function isRealTaskId(id) {
  if (!id) return false
  const s = String(id)
  if (s.startsWith('dec_') || s.startsWith('sim_') || s.startsWith('ont_')) return false
  if (s.startsWith('task_')) return true
  // 兼容旧版 TaskManager 的裸 UUID
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)
}

export const prepareSimulation = async (data = {}) => {
  const { simId, decisionId, detail } = await resolveSimContext(data)
  const stage = data.stage || 'all'
  // 以服务端决策的方案数为准，避免本地编辑器未应用的 scenarios 误判
  const scenarioCount =
    detail?.scenarios?.length ||
    detail?.matrix?.length ||
    (detail?.decision && Number(detail.decision.sample_count) > 1 ? 2 : 0) ||
    1

  // 分阶段重试（profiles / platform_config / event_config）必须走单 sim 异步 prepare，
  // 决策级 prepareDecision 不支持 stage，点重试会变成无感刷新。
  if (stage !== 'all') {
    return requestWithRetry(
      () =>
        service.post('/api/simulation/prepare', {
          simulation_id: simId,
          simulation_requirement: data.simulation_requirement,
          document_text: data.document_text,
          entity_types: data.entity_types,
          use_llm_for_profiles: data.use_llm_for_profiles ?? true,
          parallel_profile_count: data.parallel_profile_count ?? 5,
          force_regenerate: true,
          stage,
        }),
      3,
      1000,
    )
  }

  // N>1 全量准备：走决策共享世界 prepare（后台线程，status=preparing）
  if (scenarioCount > 1 && decisionId) {
    const { prepareDecision } = await import('./decision')
    const res = await prepareDecision(decisionId, {
      ...data,
      force_regenerate: data.force_regenerate ?? false,
    })
    const payload = res?.data || {}
    const status = String(payload.status || '').toLowerCase()
    const done = status === 'completed' || status === 'ready' || payload.already_prepared
    return {
      success: true,
      data: {
        // 切勿把 dec_ 当作 task_id，否则 /prepare/status 会 404
        task_id: null,
        simulation_id: simId,
        decision_id: decisionId,
        status: done ? 'completed' : status || 'preparing',
        progress: done ? 100 : Number(payload.progress) || 0,
        already_prepared: Boolean(done),
        ...payload,
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
        stage: 'all',
      }),
    3,
    1000,
  )
}

export const getPrepareStatus = async (data) => {
  const payload = typeof data === 'string' ? { simulation_id: data } : data || {}
  try {
    const { simId } = await resolveSimContext(payload)
    const taskId = isRealTaskId(payload.task_id) ? payload.task_id : undefined
    return service.post('/api/simulation/prepare/status', {
      simulation_id: simId,
      ...(taskId ? { task_id: taskId } : {}),
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

export const getRunStatus = async (id, options = {}) => {
  const raw = pickId(id) || id
  // 决策级：返回矩阵 + 兼容 Step3 单时间线字段
  if (raw && String(raw).startsWith('dec_')) {
    const st = await getDecisionStatus(raw)
    const data = st.data || {}
    const progress = data.progress || { done: 0, total: 0 }
    const status = data.status || data.decision?.status
    const completed = ['completed', 'done', 'success'].includes(String(status || '').toLowerCase())
    const running = String(status || '').toLowerCase() === 'running'
    const totalRounds = data.decision?.max_rounds || 10

    // 优先选中 sim，禁止死取 matrix[0]
    const preferred =
      options.simId ||
      options.sim_id ||
      options.selectedSimId ||
      null
    const firstSim =
      preferred ||
      data.matrix?.[0]?.runs?.[0]?.sim_id ||
      cacheGet(raw)?.simId ||
      null
    let simStatus = null
    if (firstSim) {
      try {
        const res = await service.get(`/api/simulation/${firstSim}/run-status`)
        simStatus = res?.data || null
      } catch (_) {
        /* ignore */
      }
    }

    const runner = String(simStatus?.runner_status || '').toLowerCase()
    const simCompleted =
      completed ||
      runner === 'completed' ||
      runner === 'stopped' ||
      (simStatus?.twitter_completed && simStatus?.reddit_completed)

    return {
      success: true,
      data: {
        ...data,
        ...(simStatus || {}),
        // decision.status 保留；完成态另用 runner_status / *_completed
        status: simCompleted ? 'completed' : status,
        total_rounds: simStatus?.total_rounds || totalRounds,
        twitter_running: simStatus?.twitter_running ?? (running && !simCompleted),
        reddit_running: simStatus?.reddit_running ?? (running && !simCompleted),
        twitter_completed: simStatus?.twitter_completed ?? simCompleted,
        reddit_completed: simStatus?.reddit_completed ?? simCompleted,
        // 禁止用矩阵 done/total 伪造 ROUND
        twitter_current_round: simStatus?.twitter_current_round ?? 0,
        reddit_current_round: simStatus?.reddit_current_round ?? 0,
        twitter_actions_count: simStatus?.twitter_actions_count ?? 0,
        reddit_actions_count: simStatus?.reddit_actions_count ?? 0,
        runner_status: simStatus?.runner_status || (simCompleted ? 'completed' : running ? 'running' : 'idle'),
        matrix: data.matrix,
        progress,
        decision_id: raw,
        sim_id: firstSim,
      },
    }
  }
  const { simId } = await resolveSimContext(id)
  return service.get(`/api/simulation/${simId}/run-status`)
}

export const getRunStatusDetail = async (id, options = {}) => {
  const raw = pickId(id) || id
  if (raw && String(raw).startsWith('dec_')) {
    const st = await getRunStatus(raw)
    const matrix = st.data?.matrix || []
    const preferred =
      options.simId ||
      options.sim_id ||
      options.selectedSimId ||
      null
    const simIds = preferred
      ? [preferred]
      : matrix
          .flatMap((m) => (m.runs || []).map((r) => r.sim_id || r.run_id))
          .filter(Boolean)

    const all_actions = []
    await Promise.all(
      simIds.slice(0, preferred ? 1 : 6).map(async (sid) => {
        try {
          const res = await service.get(`/api/simulation/${sid}/actions`, {
            params: { limit: 120 },
          })
          const actions = res.data?.actions || res.data || []
          for (const a of actions) {
            // 过滤空壳 LLM_ACTION
            const t = String(a.action_type || '').toUpperCase()
            const args = a.action_args || {}
            const content =
              a.content || args.content || args.quote_content || args.post_content || ''
            if (t === 'LLM_ACTION' && !String(content).trim()) continue
            all_actions.push({
              ...a,
              platform: a.platform || 'twitter',
              sim_id: sid,
              action_args: {
                ...args,
                ...(content && !args.content ? { content } : {}),
              },
            })
          }
        } catch (_) {
          /* ignore */
        }
      }),
    )
    all_actions.sort((a, b) =>
      String(a.timestamp || a.round || '').localeCompare(String(b.timestamp || b.round || '')),
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

/** 历史任务库：一条 = 一个决策任务（对齐 MiroFish「一条 = 一次 simulation」）
 * 本体是任务背后的资源，不单独占卡。
 */
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
    const activity = d.activity || {}
    const rounds = activity.rounds || {}
    return {
      kind: 'decision',
      simulation_id: d.id,
      project_id: d.ontology_id,
      report_id: d.id,
      decision_id: d.id,
      ontology_id: d.ontology_id,
      simulation_requirement: d.title || d.id,
      status: d.status,
      activity,
      is_running: Boolean(activity.is_running),
      workflow_step: Number(activity.workflow_step || 0) || null,
      workflow_step_key: activity.workflow_step_key || '',
      stage: activity.stage || '',
      stage_message: activity.message || '',
      stage_progress: Number(activity.progress || 0),
      created_at: d.created_at,
      current_round: Number(rounds.current || 0),
      total_rounds: Number(rounds.total || 0) || 1,
      sample_count: n,
      files: docsByOntology[d.ontology_id] || [],
    }
  })

  return { success: true, data: fromDecisions }
}
