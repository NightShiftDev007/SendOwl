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
            {{ { graph: $t('main.layoutGraph'), split: $t('main.layoutSplit'), workbench: $t('main.layoutWorkbench') }[mode] }}
          </button>
        </div>
      </template>
      <template #right>
        <div class="workflow-step">
          <span class="step-num">本体工作台</span>
          <span class="step-name">{{ ontologyId === 'new' ? '新建' : ontologyId }}</span>
        </div>
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
        <div class="workbench">
          <div class="scroll-container">
            <div class="step-card" :class="phaseClass(0)">
              <div class="card-header">
                <span class="card-index">01</span>
                <span class="card-title">创建本体</span>
                <span class="badge" :class="badgeClass(0)">{{ badgeText(0) }}</span>
              </div>
              <p class="api-note">POST /api/ontology/create</p>
              <p class="card-desc">上传种子文档并生成/锁定舆情模板 schema，形成常驻本体记录。</p>
              <p v-if="projectData" class="mono-line">id={{ projectData.id }} · {{ projectData.name }}</p>
            </div>

            <div class="step-card" :class="phaseClass(1)">
              <div class="card-header">
                <span class="card-index">02</span>
                <span class="card-title">建图</span>
                <span class="badge" :class="badgeClass(1)">{{ badgeText(1) }}</span>
              </div>
              <p class="api-note">POST /api/ontology/:id/build</p>
              <p class="card-desc">向 Zep 写入 episode，抽取实体关系；进度写入系统日志。</p>
              <div v-if="buildProgress" class="progress-line">
                {{ buildProgress.message || 'building…' }}
                <span v-if="buildProgress.progress != null"> · {{ buildProgress.progress }}%</span>
              </div>
              <button class="cta" :disabled="currentPhase < 0 || building" @click="startBuildGraph">
                {{ building ? '建图中…' : '开始/重试建图' }}
              </button>
            </div>

            <div class="step-card" :class="phaseClass(2)">
              <div class="card-header">
                <span class="card-index">03</span>
                <span class="card-title">快照版本</span>
                <span class="badge" :class="badgeClass(2)">{{ badgeText(2) }}</span>
              </div>
              <p class="api-note">POST /api/ontology/:id/snapshot</p>
              <p class="card-desc">导出本地 JSON 快照，作为后续世界切片与推演的可复现数据源。</p>
              <button class="cta" :disabled="!projectData?.id" @click="doSnapshot">导出版本快照</button>
              <button class="cta secondary" :disabled="!projectData?.id" @click="goCreateDecision">
                基于此本体创建决策 →
              </button>
              <ul class="version-list" v-if="versions.length">
                <li v-for="v in versions" :key="v.id" class="mono-line">
                  v{{ v.version }} · {{ v.id }}
                </li>
              </ul>
            </div>
          </div>

          <div class="system-logs">
            <div class="logs-title">SYSTEM DASHBOARD</div>
            <div class="logs-body" ref="logsEl">
              <div v-for="(log, i) in systemLogs" :key="i" class="log-line">
                <span class="log-time">{{ log.time }}</span>
                <span class="log-msg">{{ log.msg }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
import GraphPanel from '../components/GraphPanel.vue'
import {
  generateOntology,
  getOntology,
  buildOntology,
  getBuildStatus,
  getOntologyGraph,
  snapshotOntology,
  listVersions,
} from '../api/ontology'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'

const route = useRoute()
const router = useRouter()

const viewMode = ref('split')
const ontologyId = ref(route.params.ontologyId || route.params.projectId)
const loading = ref(false)
const building = ref(false)
const graphLoading = ref(false)
const error = ref('')
const projectData = ref(null)
const graphData = ref(null)
const currentPhase = ref(-1)
const buildProgress = ref(null)
const systemLogs = ref([])
const versions = ref([])
const logsEl = ref(null)

let pollTimer = null

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
  if (currentPhase.value === 0) return 'Creating Ontology'
  return 'Initializing'
})

function phaseClass(n) {
  if (currentPhase.value === n) return 'active'
  if (currentPhase.value > n) return 'done'
  return ''
}
function badgeClass(n) {
  if (currentPhase.value > n) return 'ok'
  if (currentPhase.value === n) return 'run'
  return 'pending'
}
function badgeText(n) {
  if (currentPhase.value > n) return 'DONE'
  if (currentPhase.value === n) return 'ACTIVE'
  return 'PENDING'
}

const addLog = async (msg) => {
  const now = new Date()
  const time =
    now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    '.' +
    now.getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 100) systemLogs.value.shift()
  await nextTick()
  if (logsEl.value) logsEl.value.scrollTop = logsEl.value.scrollHeight
}

const toggleMaximize = (target) => {
  viewMode.value = viewMode.value === target ? 'split' : target
}

async function refreshVersions() {
  if (!ontologyId.value || ontologyId.value === 'new') return
  try {
    const res = await listVersions(ontologyId.value)
    versions.value = res.data || []
  } catch (_) {
    versions.value = []
  }
}

async function loadGraph() {
  if (!ontologyId.value || ontologyId.value === 'new') return
  graphLoading.value = true
  try {
    const res = await getOntologyGraph(ontologyId.value)
    if (res.success) {
      graphData.value = res.data
      addLog(
        `Graph loaded. Nodes: ${res.data.nodes?.length || 0}, Edges: ${res.data.edges?.length || 0}`,
      )
    }
  } catch (e) {
    addLog(`Graph not ready: ${e.message}`)
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => loadGraph()

async function handleNewOntology() {
  const pending = getPendingUpload()
  if (!pending.isPending || pending.files.length === 0) {
    error.value = 'No pending files found.'
    addLog('Error: No pending files for new ontology.')
    return
  }
  try {
    loading.value = true
    currentPhase.value = 0
    addLog('Creating ontology: uploading files...')
    const formData = new FormData()
    pending.files.forEach((f) => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)
    formData.append('name', pending.simulationRequirement.slice(0, 40) || '未命名本体')
    formData.append('template', 'opinion')
    const res = await generateOntology(formData)
    clearPendingUpload()
    projectData.value = res.data
    ontologyId.value = res.data.id
    router.replace({ name: 'OntologyWorkspace', params: { ontologyId: res.data.id } })
    addLog(`Ontology created: ${res.data.id}`)
    await startBuildGraph()
  } catch (err) {
    error.value = err.message
    addLog(`Exception creating ontology: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function loadOntology() {
  try {
    loading.value = true
    addLog(`Loading ontology ${ontologyId.value}...`)
    const res = await getOntology(ontologyId.value)
    projectData.value = res.data
    const st = res.data.status
    if (st === 'ready') {
      currentPhase.value = 2
      await loadGraph()
      await refreshVersions()
    } else if (st === 'building') {
      currentPhase.value = 1
      startPolling()
    } else {
      currentPhase.value = 0
    }
    addLog(`Ontology loaded. Status: ${st}`)
  } catch (err) {
    error.value = err.message
    addLog(`Exception loading ontology: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function startBuildGraph() {
  if (!ontologyId.value || ontologyId.value === 'new') return
  try {
    building.value = true
    currentPhase.value = 1
    buildProgress.value = { progress: 0, message: 'Starting build...' }
    addLog('Initiating graph build...')
    const res = await buildOntology(ontologyId.value, { use_existing_schema: true, async: true })
    addLog(`Build task: ${res.data?.task_id || 'sync'}`)
    if (res.data?.task_id) {
      startPolling(res.data.task_id)
    } else {
      currentPhase.value = 2
      await loadGraph()
      await doSnapshot()
    }
  } catch (err) {
    error.value = err.message
    addLog(`Build failed: ${err.message}`)
  } finally {
    building.value = false
  }
}

function startPolling(taskId) {
  stopPolling()
  const tid = taskId
  pollTimer = setInterval(async () => {
    try {
      const res = await getBuildStatus(ontologyId.value, tid)
      const task = res.data || {}
      buildProgress.value = {
        progress: task.progress || 0,
        message: task.message || task.status,
      }
      if (task.message) addLog(task.message)
      if (['completed', 'success', 'ready'].includes(task.status)) {
        stopPolling()
        currentPhase.value = 2
        addLog('Graph build completed.')
        await loadGraph()
        await doSnapshot()
      } else if (['failed', 'error'].includes(task.status)) {
        stopPolling()
        error.value = task.error || 'build failed'
        addLog(`Build failed: ${error.value}`)
      }
    } catch (e) {
      console.error(e)
    }
  }, 2500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function doSnapshot() {
  try {
    addLog('Creating snapshot...')
    const res = await snapshotOntology(ontologyId.value)
    addLog(`Snapshot: ${res.data?.id || 'ok'}`)
    currentPhase.value = 2
    await refreshVersions()
    await loadGraph()
  } catch (e) {
    addLog(`Snapshot failed: ${e.message}`)
  }
}

function goCreateDecision() {
  router.push({
    name: 'DecisionCreate',
    query: { ontology_id: ontologyId.value },
  })
}

onMounted(async () => {
  addLog('Ontology workspace initialized.')
  if (ontologyId.value === 'new') {
    await handleNewOntology()
  } else {
    await loadOntology()
  }
})

onUnmounted(stopPolling)
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
}
.switch-btn.active {
  background: #fff;
  color: #000;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.step-divider {
  width: 1px;
  height: 20px;
  background: var(--border);
}
.workflow-step {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-size: 12px;
}
.step-num {
  font-family: var(--font-mono);
  font-weight: 700;
}
.step-name {
  color: #888;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
}
.status-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
  animation: pulse 1.2s infinite;
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
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.35s ease, opacity 0.3s ease, transform 0.3s ease;
}
.panel-wrapper.left {
  border-right: 1px solid #eaeaea;
}
.workbench {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fafafa;
}
.scroll-container {
  flex: 1;
  overflow: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.step-card {
  background: #fff;
  border: 1px solid #eaeaea;
  border-radius: 4px;
  padding: 16px;
}
.step-card.active {
  border-color: var(--brand);
}
.step-card.done {
  border-color: #a7f3d0;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.card-index {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--brand);
}
.card-title {
  font-weight: 700;
  flex: 1;
}
.badge {
  font-size: 10px;
  font-family: var(--font-mono);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  color: var(--ink-faint);
}
.badge.ok {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 30%, #fff);
  background: color-mix(in srgb, var(--success) 8%, #fff);
}
.badge.run {
  color: var(--brand);
  border-color: color-mix(in srgb, var(--brand) 30%, #fff);
  background: var(--brand-soft);
}
.api-note {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  margin: 0 0 8px;
}
.card-desc {
  font-size: 13px;
  color: var(--ink-secondary);
  line-height: 1.55;
  margin: 0 0 12px;
}
.progress-line {
  font-size: 12px;
  color: var(--ink-muted);
  margin-bottom: 10px;
  font-family: var(--font-mono);
}
.cta {
  width: 100%;
  border: none;
  background: var(--ink);
  color: var(--bg);
  padding: 12px;
  font-weight: 600;
  cursor: pointer;
  margin-bottom: 8px;
}
.cta:hover:not(:disabled) {
  background: var(--brand);
}
.cta:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.cta.secondary {
  background: var(--bg);
  color: var(--ink);
  border: 1px solid var(--border-strong);
}
.cta.secondary:hover:not(:disabled) {
  background: var(--ink);
  color: var(--bg);
}
.mono-line {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  margin: 4px 0;
}
.version-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
.system-logs {
  background: #000;
  color: #ccc;
  height: 110px;
  display: flex;
  flex-direction: column;
}
.logs-title {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  padding: 8px 12px;
  border-bottom: 1px solid #222;
  color: #888;
}
.logs-body {
  flex: 1;
  overflow: auto;
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
}
.log-line {
  margin-bottom: 2px;
}
.log-time {
  color: #666;
  margin-right: 8px;
}
</style>
