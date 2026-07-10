/**
 * 兼容层：旧 MiroFish simulation API → 决策中心 decision/run API
 */
import { listOntologies } from './ontology'
import {
  getDecision,
  getDecisionStatus,
  startDecision,
  getRunActions,
  interviewRun,
  listDecisions,
} from './decision'

export const createSimulation = async () => {
  throw new Error('请使用创建决策页 /decision/new')
}

export const prepareSimulation = async () => ({
  success: true,
  data: { status: 'skipped', message: '由 Scenario Runner 自动准备世界切片' },
})

export const getPrepareStatus = async () => ({
  success: true,
  data: { status: 'completed', progress: 100 },
})

export const getSimulation = (id) => getDecision(id)
export const listSimulations = () => listDecisions()

export const startSimulation = (data) =>
  startDecision(data.simulation_id || data.decision_id, data)

export const stopSimulation = async () => ({ success: true })

export const getRunStatus = (id) => getDecisionStatus(id)

export const getRunStatusDetail = async (id) => {
  const st = await getDecisionStatus(id)
  return {
    success: true,
    data: {
      ...(st.data || {}),
      all_actions: [],
    },
  }
}

export const getSimulationPosts = async () => ({
  success: true,
  data: { posts: [] },
})

export const getSimulationProfiles = async () => ({
  success: true,
  data: { profiles: [] },
})

export const getSimulationProfilesRealtime = getSimulationProfiles
export const getSimulationConfig = async () => ({ success: true, data: {} })
export const getSimulationConfigRealtime = getSimulationConfig

export const interviewAgent = (data) =>
  interviewRun(data.simulation_id || data.run_id, {
    agent_id: data.agent_id,
    prompt: data.prompt || data.question,
  })

export const getActions = (runId, params) => getRunActions(runId, params)

/** 历史库：合并决策任务 + 本体 */
export const getSimulationHistory = async (limit = 20) => {
  const [ontologies, decisions] = await Promise.all([
    listOntologies().catch(() => ({ data: [] })),
    listDecisions().catch(() => ({ data: [] })),
  ])
  const ontList = ontologies.data || []
  const decList = decisions.data || []

  const fromDecisions = decList.slice(0, limit).map((d) => ({
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
    files: [],
  }))

  const remain = Math.max(0, limit - fromDecisions.length)
  const fromOntologies = ontList.slice(0, remain).map((o) => ({
    kind: 'ontology',
    simulation_id: o.id,
    project_id: o.id,
    report_id: null,
    ontology_id: o.id,
    simulation_requirement: o.name || o.id,
    status: o.status,
    created_at: o.created_at,
    current_round: o.status === 'ready' ? 1 : 0,
    total_rounds: 1,
    files: [],
  }))

  return { success: true, data: [...fromDecisions, ...fromOntologies].slice(0, limit) }
}
