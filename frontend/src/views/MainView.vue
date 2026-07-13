<template>
  <div class="main-view">
    <AppHeader>
      <template #center>
        <div class="view-switcher">
          <button
            v-for="mode in ['graph', 'split', 'workbench']"
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{
              {
                graph: $t('main.layoutGraph'),
                split: $t('main.layoutSplit'),
                workbench: $t('main.layoutWorkbench'),
              }[mode]
            }}
          </button>
        </div>
      </template>
      <template #right>
        <StepNav :current-step="1" :decision-id="currentDecisionId" />
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </template>
    </AppHeader>

    <main class="content-area">
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="currentPhase"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step1GraphBuild
          v-if="currentStep === 1"
          :currentPhase="currentPhase"
          :projectData="projectData"
          :ontologyProgress="ontologyProgress"
          :buildProgress="buildProgress"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @next-step="handleNextStep"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
/**
 * Step1 本体/建图工作台 —— 结构对齐 MiroFish MainView，
 * 数据层走 ontology API（project_id ≡ ontology_id）。
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppHeader from '../components/AppHeader.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import StepNav from '../components/StepNav.vue'
import {
  generateOntology,
  getProject,
  buildGraph,
  getBuildStatus,
  getOntologyGraph,
  snapshotOntology,
} from '../api/graph'
import { createSimulation } from '../api/simulation'
import { getDecision } from '../api/decision'
import { subscribeTask } from '../api/sse'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'
import { touchWorkflowStep } from '../store/workflowContext'
import { taskRoute } from '../utils/taskRoute'

const props = defineProps({
  decisionId: String,
})

const route = useRoute()
const router = useRouter()
const { t, tm } = useI18n()

const viewMode = ref('split')
const currentStep = ref(1)
const stepNames = computed(() => tm('main.stepNames'))

/** 路由主 ID：dec_*（或瞬态 new） */
const currentDecisionId = ref(props.decisionId || route.params.decisionId || 'new')
/** 派生资源：真实 ontology */
const ontologyId = ref('')
const loading = ref(false)
const graphLoading = ref(false)
const error = ref('')
const projectData = ref(null)
const graphData = ref(null)
const currentPhase = ref(-1)
const ontologyProgress = ref(null)
const buildProgress = ref(null)
const systemLogs = ref([])

let pollTimer = null
let taskSse = null

const leftPanelStyle = computed(() => {
  if (viewMode.value === 'graph') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'workbench') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const statusClass = computed(() => {
  if (error.value) return 'error'
  if (currentPhase.value >= 2) return 'completed'
  return 'processing'
})

const statusText = computed(() => {
  if (error.value) return 'Error'
  if (currentPhase.value >= 2) return 'Ready'
  if (currentPhase.value === 1) return 'Building Graph'
  if (currentPhase.value === 0) return 'Generating Ontology'
  return 'Initializing'
})

function normalizeProject(raw) {
  if (!raw) return null
  const id = raw.id || raw.project_id || raw.ontology_id
  return {
    ...raw,
    id,
    project_id: id,
    ontology_id: id,
    ontology: raw.ontology || raw.schema || null,
    schema: raw.schema || raw.ontology || null,
    simulation_requirement: raw.simulation_requirement || raw.name || '',
  }
}

const addLog = (msg) => {
  const time =
    new Date().toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }) +
    '.' +
    new Date().getMilliseconds().toString().padStart(3, '0')
  console.log(`[SandOwl ${time}] ${msg}`)
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 100) systemLogs.value.shift()
}

const toggleMaximize = (target) => {
  viewMode.value = viewMode.value === target ? 'split' : target
}

const handleNextStep = () => {
  /* Step1 通过 createSimulation 自行跳到 /tasks/:decisionId/environment */
}

const initProject = async () => {
  addLog('Project view initialized.')
  void t
  void stepNames
  const id = currentDecisionId.value
  if (id === 'new') {
    await handleNewProject()
    return
  }
  if (String(id).startsWith('dec_')) {
    await loadFromDecision(id)
    return
  }
  // 兼容：若误传入 ont_*，先解析/创建决策后再加载
  ontologyId.value = id
  await loadProject()
}

const loadFromDecision = async (decisionId) => {
  try {
    loading.value = true
    addLog(`Loading task ${decisionId}...`)
    const res = await getDecision(decisionId)
    const payload = res?.data || res
    // API 形如 { decision: { ontology_id }, scenarios, ... }
    const decision = payload?.decision || payload
    const oid =
      decision?.ontology_id ||
      decision?.project_id ||
      payload?.ontology_id ||
      payload?.project_id
    if (!oid) {
      error.value = '任务缺少 ontology_id'
      addLog(`Error: decision ${decisionId} has no ontology_id`)
      return
    }
    currentDecisionId.value = decisionId
    ontologyId.value = oid
    touchWorkflowStep(1, { decisionId, ontologyId: oid })
    await loadProject()
  } catch (err) {
    error.value = err.message
    addLog(`Exception loading decision: ${err.message}`)
  } finally {
    loading.value = false
  }
}

const handleNewProject = async () => {
  const pending = getPendingUpload()
  if (!pending.isPending || pending.files.length === 0) {
    error.value = 'No pending files found.'
    addLog('Error: No pending files found for new project.')
    return
  }

  try {
    loading.value = true
    currentPhase.value = 0
    ontologyProgress.value = { message: 'Uploading and analyzing docs...' }
    addLog('Starting ontology generation: Uploading files...')

    const formData = new FormData()
    pending.files.forEach((f) => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)
    formData.append('name', pending.simulationRequirement.slice(0, 40) || '未命名本体')
    formData.append('template', 'opinion')

    const res = await generateOntology(formData)
    if (res.success) {
      clearPendingUpload()
      const id = res.data.id || res.data.project_id
      ontologyId.value = id
      projectData.value = normalizeProject(res.data)
      ontologyProgress.value = null
      addLog(`Ontology generated successfully for project ${id}`)

      // 点启动引擎即创建任务（Decision），地址栏改为 /tasks/dec_xxx/graph
      let decId = null
      try {
        const taskRes = await createSimulation({
          ontology_id: id,
          project_id: id,
          title:
            pending.simulationRequirement?.slice(0, 40)?.trim() ||
            res.data?.name?.slice(0, 40) ||
            `任务 ${String(id).slice(0, 8)}`,
        })
        decId = taskRes?.data?.decision_id || taskRes?.data?.simulation_id
        if (decId) {
          addLog(`Task created: ${decId}`)
          currentDecisionId.value = decId
          touchWorkflowStep(1, { decisionId: decId, ontologyId: id })
          router.replace(taskRoute(1, decId))
        } else {
          addLog('Task create returned without decision_id (will retry at Step1 exit)')
        }
      } catch (taskErr) {
        addLog(`Task create deferred: ${taskErr.message}`)
      }

      await startBuildGraph()
    } else {
      error.value = res.error || 'Ontology generation failed'
      addLog(`Error generating ontology: ${error.value}`)
    }
  } catch (err) {
    error.value = err.message
    addLog(`Exception in handleNewProject: ${err.message}`)
  } finally {
    loading.value = false
  }
}

const loadProject = async () => {
  try {
    loading.value = true
    if (!ontologyId.value) {
      error.value = '缺少 ontologyId'
      return
    }
    addLog(`Loading ontology ${ontologyId.value}...`)
    const res = await getProject(ontologyId.value)
    if (res.success) {
      projectData.value = normalizeProject(res.data)
      updatePhaseByStatus(res.data.status)
      addLog(`Project loaded. Status: ${res.data.status}`)

      const st = res.data.status
      if (['created', 'ontology_generated'].includes(st) && !res.data.graph_id) {
        await startBuildGraph()
      } else if (['building', 'graph_building'].includes(st)) {
        currentPhase.value = 1
        // 唯一主通道：task SSE（帧内带 graph）
        const buildTid =
          res.data.build_task_id || res.data.graph_build_task_id || null
        startPollingTask(buildTid)
      } else if (['ready', 'graph_completed'].includes(st) || res.data.graph_id) {
        currentPhase.value = 2
        await loadGraph()
      }
    } else {
      error.value = res.error
      addLog(`Error loading project: ${res.error}`)
    }
  } catch (err) {
    error.value = err.message
    addLog(`Exception in loadProject: ${err.message}`)
  } finally {
    loading.value = false
  }
}

const updatePhaseByStatus = (status) => {
  switch (status) {
    case 'created':
    case 'ontology_generated':
      currentPhase.value = 0
      break
    case 'building':
    case 'graph_building':
      currentPhase.value = 1
      break
    case 'ready':
    case 'graph_completed':
      currentPhase.value = 2
      break
    case 'failed':
      error.value = 'Project failed'
      break
  }
}

const startBuildGraph = async () => {
  try {
    currentPhase.value = 1
    buildProgress.value = { progress: 0, message: 'Starting build...' }
    addLog('Initiating graph build...')

    const res = await buildGraph({
      project_id: ontologyId.value,
      use_existing_schema: true,
      async: true,
    })
    if (res.success) {
      addLog(`Graph build task started. Task ID: ${res.data?.task_id || 'sync'}`)
      if (res.data?.task_id) {
        startPollingTask(res.data.task_id)
      } else {
        currentPhase.value = 2
        await finalizeBuild()
      }
    } else {
      error.value = res.error
      addLog(`Error starting build: ${res.error}`)
    }
  } catch (err) {
    error.value = err.message
    addLog(`Exception in startBuildGraph: ${err.message}`)
  }
}

const applyGraphPayload = (data) => {
  if (!data) return
  const nodes = data.nodes || []
  const edges = data.edges || []
  if (!nodes.length && !edges.length && !data.graph_id) return
  graphData.value = data
  const nodeCount = data.node_count || nodes.length || 0
  const edgeCount = data.edge_count || edges.length || 0
  addLog(`Graph data refreshed. Nodes: ${nodeCount}, Edges: ${edgeCount}`)
}

const fetchGraphData = async () => {
  try {
    const gRes = await getOntologyGraph(ontologyId.value)
    if (gRes?.success && gRes.data) {
      applyGraphPayload(gRes.data)
    }
  } catch (err) {
    console.warn('Graph fetch error:', err)
  }
}

const startPollingTask = (taskId) => {
  stopPolling()
  // 无真实 task_id：慢速探测本体状态（禁止 2s 狂刷 getOntology）
  if (!taskId || !String(taskId).startsWith('task_')) {
    let stallTicks = 0
    const tick = async () => {
      try {
        const projRes = await getProject(ontologyId.value)
        const data = projRes.data || {}
        const st = String(data.status || '').toLowerCase()
        // 中途补到 build_task_id：切到 task SSE，停掉本体轮询
        const tid = data.build_task_id || data.graph_build_task_id
        if (tid && String(tid).startsWith('task_')) {
          stopPolling()
          startPollingTask(tid)
          return
        }
        if (['ready', 'graph_completed'].includes(st) || data.graph_id) {
          stopPolling()
          currentPhase.value = 2
          await finalizeBuild()
          return
        }
        if (['failed', 'error'].includes(st)) {
          stopPolling()
          error.value = '建图失败'
          addLog('Graph build failed (ontology status)')
          currentPhase.value = 1
          return
        }
        buildProgress.value = {
          progress: buildProgress.value?.progress || 50,
          message: st || 'building',
        }
        stallTicks += 1
        // ~2 分钟仍无终态 / 无 task：停表，避免无限刷 /api/ontology/:id
        if (stallTicks >= 24) {
          stopPolling()
          addLog('建图进度停滞且无 task_id，已停止轮询。可刷新重试或重新建图。')
          error.value = '建图任务句柄丢失，请刷新或重新建图'
        }
      } catch (e) {
        console.error(e)
      }
    }
    tick()
    pollTimer = setInterval(tick, 5000)
    return
  }

  let settled = false
  const applyTask = async (task) => {
    if (!task || settled) return
    // 可重试竞态：勿当成终态失败
    if (
      task.retryable ||
      task.error === 'task_not_found' ||
      (task.status === 'pending' && task.error === 'task_not_found')
    ) {
      return
    }
    if (task.message && task.message !== buildProgress.value?.message) {
      addLog(task.message)
    }
    buildProgress.value = { progress: task.progress || 0, message: task.message }
    // 同帧图谱增量
    if (task.graph) {
      applyGraphPayload(task.graph)
    }

    if (['completed', 'success', 'ready'].includes(task.status)) {
      settled = true
      addLog('Graph build task completed.')
      stopPolling()
      currentPhase.value = 2
      await finalizeBuild()
    } else if (['failed', 'error'].includes(task.status) || task.task_lost) {
      settled = true
      stopPolling()
      error.value = task.error || '建图失败'
      addLog(`Graph build failed: ${error.value}`)
      currentPhase.value = 1
    }
  }

  taskSse = subscribeTask(taskId, {
    onOpen: () => {
      // 重连后拉一次快照补齐
      getBuildStatus(ontologyId.value, taskId)
        .then((res) => applyTask(res.data || {}))
        .catch(() => {})
    },
    onEvent: (data) => applyTask(data),
    onDone: (data) => applyTask(data),
    onError: (err) => {
      if (settled) return
      addLog(`SSE 建图进度异常，降级轮询: ${err?.message || err?.error || err}`)
      if (!pollTimer) {
        pollTimer = setInterval(() => pollTaskStatus(taskId), 3000)
      }
    },
  })
}

const pollTaskStatus = async (taskId) => {
  try {
    let task = {}
    if (taskId) {
      const res = await getBuildStatus(ontologyId.value, taskId)
      task = res.data || {}
    } else {
      const projRes = await getProject(ontologyId.value)
      const st = projRes.data?.status
      if (['ready', 'graph_completed'].includes(st)) {
        task = { status: 'completed', progress: 100, message: 'ready' }
      } else if (['failed', 'error'].includes(st)) {
        task = { status: 'failed', error: 'build failed' }
      } else {
        task = { status: 'running', progress: buildProgress.value?.progress || 50, message: st }
      }
    }

    if (task.message && task.message !== buildProgress.value?.message) {
      addLog(task.message)
    }
    buildProgress.value = { progress: task.progress || 0, message: task.message }

    if (['completed', 'success', 'ready'].includes(task.status)) {
      addLog('Graph build task completed.')
      stopPolling()
      currentPhase.value = 2
      await finalizeBuild()
    } else if (['failed', 'error'].includes(task.status) || task.task_lost) {
      stopPolling()
      error.value = task.error || '建图失败'
      addLog(`Graph build failed: ${error.value}`)
      currentPhase.value = 1
    }
  } catch (e) {
    console.error(e)
  }
}

async function finalizeBuild() {
  // 先落快照，再读图；失败则短重试避免竞态
  for (let i = 0; i < 5; i++) {
    try {
      await snapshotOntology(ontologyId.value)
      addLog('Snapshot exported.')
      break
    } catch (e) {
      if (i === 4) addLog(`Snapshot skipped: ${e.message}`)
      else await new Promise((r) => setTimeout(r, 800))
    }
  }
  const projRes = await getProject(ontologyId.value)
  if (projRes.success) {
    projectData.value = normalizeProject(projRes.data)
  }
  await loadGraph()
}

const loadGraph = async () => {
  graphLoading.value = true
  addLog(`Loading graph data: ${ontologyId.value}`)
  try {
    const res = await getOntologyGraph(ontologyId.value)
    if (res?.success) {
      graphData.value = res.data
      addLog('Graph data loaded successfully.')
    } else {
      addLog(`Failed to load graph data: ${res?.error || 'unknown'}`)
    }
  } catch (e) {
    addLog(`Exception loading graph: ${e.message}`)
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = async () => {
  addLog('Manual graph refresh triggered.')
  graphLoading.value = true
  try {
    if (ontologyId.value) {
      await snapshotOntology(ontologyId.value).catch(() => null)
    }
    await loadGraph()
  } finally {
    graphLoading.value = false
  }
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (taskSse) {
    try {
      taskSse.close()
    } catch (_) {
      /* ignore */
    }
    taskSse = null
  }
}

onMounted(() => {
  initProject()
})

watch(
  () => route.params.decisionId,
  (newId, oldId) => {
    if (!newId || newId === oldId || newId === currentDecisionId.value) return
    currentDecisionId.value = newId
    ontologyId.value = ''
    projectData.value = null
    graphData.value = null
    initProject()
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
  font-family: var(--font-sans);
}

.view-switcher {
  display: flex;
  background: #f5f5f5;
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  color: #666;
  font-family: var(--font-sans);
  transition: all 0.2s;
}

.switch-btn:hover {
  color: #000;
}

.switch-btn.active {
  background: #fff;
  color: #000;
  font-weight: 500;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.step-divider {
  width: 1px;
  height: 20px;
  background: #eee;
}

.workflow-step {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.2;
}

.step-num {
  font-size: 11px;
  font-weight: 700;
  color: #000;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-family: var(--font-mono);
}

.step-name {
  font-size: 10px;
  color: #888;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #666;
  font-family: var(--font-mono);
}

.status-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1.5s infinite;
}

.status-indicator.completed .dot {
  background: #10b981;
  animation: none;
}

.status-indicator.error .dot {
  background: #ef4444;
  animation: none;
}

@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
  100% {
    opacity: 1;
  }
}

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease,
    transform 0.3s ease;
  will-change: width, opacity, transform;
}

.panel-wrapper.left {
  border-right: 1px solid #eaeaea;
}
</style>
