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
        <StepNav :current-step="1" :project-id="currentProjectId" />
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
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
  getOntologyGraphLive,
  snapshotOntology,
} from '../api/graph'
import { createSimulation } from '../api/simulation'
import { subscribeTask } from '../api/sse'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'

const route = useRoute()
const router = useRouter()
const { t, tm } = useI18n()

const viewMode = ref('split')
const currentStep = ref(1)
const stepNames = computed(() => tm('main.stepNames'))

const currentProjectId = ref(route.params.projectId || route.params.ontologyId)
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
let graphPollTimer = null
let taskSse = null
let lastGraphRefreshAt = 0
const GRAPH_REFRESH_MIN_MS = 5000

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
  /* Step1 通过 createSimulation 自行跳到 /simulation/:id */
}

const initProject = async () => {
  addLog('Project view initialized.')
  void t
  void stepNames
  if (currentProjectId.value === 'new') {
    await handleNewProject()
  } else {
    await loadProject()
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
      currentProjectId.value = id
      projectData.value = normalizeProject(res.data)
      router.replace({ name: 'Process', params: { projectId: id } })
      ontologyProgress.value = null
      addLog(`Ontology generated successfully for project ${id}`)

      // 点启动引擎即创建任务（Decision），失败不阻断建图；Step1 完成时可兜底复用/创建
      try {
        const taskRes = await createSimulation({
          ontology_id: id,
          project_id: id,
          title:
            pending.simulationRequirement?.slice(0, 40)?.trim() ||
            res.data?.name?.slice(0, 40) ||
            `任务 ${String(id).slice(0, 8)}`,
        })
        const decId = taskRes?.data?.decision_id || taskRes?.data?.simulation_id
        if (decId) {
          addLog(`Task created: ${decId}`)
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
    addLog(`Loading project ${currentProjectId.value}...`)
    const res = await getProject(currentProjectId.value)
    if (res.success) {
      projectData.value = normalizeProject(res.data)
      updatePhaseByStatus(res.data.status)
      addLog(`Project loaded. Status: ${res.data.status}`)

      const st = res.data.status
      if (['created', 'ontology_generated'].includes(st) && !res.data.graph_id) {
        await startBuildGraph()
      } else if (['building', 'graph_building'].includes(st)) {
        currentPhase.value = 1
        startGraphPolling()
        // 无 task_id 时仍轮询本体状态
        startPollingTask(res.data.graph_build_task_id || null)
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
      project_id: currentProjectId.value,
      use_existing_schema: true,
      async: true,
    })
    if (res.success) {
      addLog(`Graph build task started. Task ID: ${res.data?.task_id || 'sync'}`)
      startGraphPolling()
      if (res.data?.task_id) {
        startPollingTask(res.data.task_id)
      } else {
        stopGraphPolling()
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

const maybeRefreshGraph = (force = false) => {
  const now = Date.now()
  if (!force && now - lastGraphRefreshAt < GRAPH_REFRESH_MIN_MS) return
  lastGraphRefreshAt = now
  fetchGraphData()
}

const startGraphPolling = () => {
  // 不再固定间隔轮询：首拉一次，后续由 task SSE 事件节流触发
  addLog('Started graph refresh (SSE-driven)...')
  maybeRefreshGraph(true)
}

const fetchGraphData = async () => {
  try {
    // 建图中优先 live；尚无 graph_id/快照时 404 属正常，静默忽略
    let gRes
    try {
      gRes = await getOntologyGraphLive(currentProjectId.value)
    } catch (_) {
      gRes = null
    }
    if (!gRes?.success) {
      try {
        gRes = await getOntologyGraph(currentProjectId.value)
      } catch (_) {
        return
      }
    }
    if (gRes?.success && gRes.data) {
      graphData.value = gRes.data
      const nodeCount = gRes.data.node_count || gRes.data.nodes?.length || 0
      const edgeCount = gRes.data.edge_count || gRes.data.edges?.length || 0
      addLog(`Graph data refreshed. Nodes: ${nodeCount}, Edges: ${edgeCount}`)
    }
  } catch (err) {
    console.warn('Graph fetch error:', err)
  }
}

const startPollingTask = (taskId) => {
  stopPolling()
  // 无真实 task_id：降级轮询本体状态
  if (!taskId || !String(taskId).startsWith('task_')) {
    pollTimer = setInterval(() => pollTaskStatus(null), 2000)
    pollTaskStatus(null)
    return
  }

  let settled = false
  const applyTask = async (task) => {
    if (!task || settled) return
    if (task.message && task.message !== buildProgress.value?.message) {
      addLog(task.message)
    }
    buildProgress.value = { progress: task.progress || 0, message: task.message }
    maybeRefreshGraph()

    if (['completed', 'success', 'ready'].includes(task.status)) {
      settled = true
      addLog('Graph build task completed.')
      stopPolling()
      stopGraphPolling()
      currentPhase.value = 2
      await finalizeBuild()
    } else if (['failed', 'error'].includes(task.status) || task.task_lost) {
      settled = true
      stopPolling()
      stopGraphPolling()
      error.value = task.error || '建图失败'
      addLog(`Graph build failed: ${error.value}`)
      currentPhase.value = 1
    }
  }

  taskSse = subscribeTask(taskId, {
    onOpen: () => {
      // 重连后拉一次快照补齐
      getBuildStatus(currentProjectId.value, taskId)
        .then((res) => applyTask(res.data || {}))
        .catch(() => {})
      maybeRefreshGraph(true)
    },
    onEvent: (data) => applyTask(data),
    onDone: (data) => applyTask(data),
    onError: (err) => {
      if (settled) return
      addLog(`SSE 建图进度异常，降级轮询: ${err?.message || err?.error || err}`)
      // 降级：短轮询兜底 + 图谱低频刷新
      if (!pollTimer) {
        pollTimer = setInterval(() => pollTaskStatus(taskId), 3000)
      }
      if (!graphPollTimer) {
        graphPollTimer = setInterval(() => maybeRefreshGraph(true), 10000)
      }
    },
  })
}

const pollTaskStatus = async (taskId) => {
  try {
    let task = {}
    if (taskId) {
      const res = await getBuildStatus(currentProjectId.value, taskId)
      task = res.data || {}
    } else {
      const projRes = await getProject(currentProjectId.value)
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
    maybeRefreshGraph()

    if (['completed', 'success', 'ready'].includes(task.status)) {
      addLog('Graph build task completed.')
      stopPolling()
      stopGraphPolling()
      currentPhase.value = 2
      await finalizeBuild()
    } else if (['failed', 'error'].includes(task.status) || task.task_lost) {
      stopPolling()
      stopGraphPolling()
      error.value = task.error || '建图失败'
      addLog(`Graph build failed: ${error.value}`)
      currentPhase.value = 1
    }
  } catch (e) {
    console.error(e)
  }
}

async function finalizeBuild() {
  // 先落快照，再读图；失败则用 live，并短重试避免竞态
  for (let i = 0; i < 5; i++) {
    try {
      await snapshotOntology(currentProjectId.value)
      addLog('Snapshot exported.')
      break
    } catch (e) {
      if (i === 4) addLog(`Snapshot skipped: ${e.message}`)
      else await new Promise((r) => setTimeout(r, 800))
    }
  }
  const projRes = await getProject(currentProjectId.value)
  if (projRes.success) {
    projectData.value = normalizeProject(projRes.data)
  }
  await loadGraph()
}

const loadGraph = async () => {
  graphLoading.value = true
  addLog(`Loading graph data: ${currentProjectId.value}`)
  try {
    let res
    try {
      res = await getOntologyGraphLive(currentProjectId.value)
    } catch (_) {
      res = null
    }
    if (!res?.success) {
      res = await getOntologyGraph(currentProjectId.value)
    }
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

const refreshGraph = () => {
  addLog('Manual graph refresh triggered.')
  loadGraph()
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

const stopGraphPolling = () => {
  if (graphPollTimer) {
    clearInterval(graphPollTimer)
    graphPollTimer = null
  }
}

onMounted(() => {
  initProject()
})

onUnmounted(() => {
  stopPolling()
  stopGraphPolling()
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
