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
        <StepNav
          :current-step="3"
          :decision-id="currentDecisionId"
        />
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </template>
    </AppHeader>

    <!-- Main Content Area -->
    <main class="content-area">
      <!-- Left Panel: Graph -->
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel 
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="3"
          :isSimulating="isSimulating"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <!-- Right Panel: Step3 开始模拟 -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step3Simulation
          :decisionId="currentDecisionId"
          :simulationId="resolvedSimulationId"
          :maxRounds="maxRounds"
          :minutesPerRound="minutesPerRound"
          :projectData="projectData"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @go-back="handleGoBack"
          @next-step="handleNextStep"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import StepNav from '../components/StepNav.vue'
import { getProject, getOntologyGraph, snapshotOntology } from '../api/graph'
import { getSimulation, getSimulationConfig, stopSimulation, closeSimulationEnv, getEnvStatus, resolveSimContext } from '../api/simulation'
import { subscribeDecision } from '../api/sse'
import { useI18n } from 'vue-i18n'
import { touchWorkflowStep } from '../store/workflowContext'
import { taskRoute } from '../utils/taskRoute'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// Props
const props = defineProps({
  decisionId: String,
})

// Layout State
const viewMode = ref('split')

// Data State
const currentDecisionId = ref(props.decisionId || route.params.decisionId)
const resolvedSimulationId = ref('')
// 直接在初始化时从 query 参数获取 maxRounds，确保子组件能立即获取到值
const maxRounds = ref(route.query.maxRounds ? parseInt(route.query.maxRounds) : null)
const minutesPerRound = ref(30) // 默认每轮30分钟
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const systemLogs = ref([])
const currentStatus = ref('processing') // processing | completed | error

// --- Computed Layout Styles ---
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

// --- Status Computed ---
const statusClass = computed(() => {
  return currentStatus.value
})

const statusText = computed(() => {
  if (currentStatus.value === 'error') return 'Error'
  if (currentStatus.value === 'completed') return 'Completed'
  return 'Running'
})

const isSimulating = computed(() => currentStatus.value === 'processing')

// --- Helpers ---
const addLog = (msg) => {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  console.log(`[SandOwl ${time}] ${msg}`)
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 200) {
    systemLogs.value.shift()
  }
}

const updateStatus = (status) => {
  currentStatus.value = status
}

// --- Layout Methods ---
const toggleMaximize = (target) => {
  if (viewMode.value === target) {
    viewMode.value = 'split'
  } else {
    viewMode.value = target
  }
}

const handleGoBack = async () => {
  // 在返回 Step 2 之前，先关闭正在运行的模拟
  addLog(t('log.preparingGoBack'))
  
  // 停止轮询
  stopGraphRefresh()
  
  try {
    // 先尝试优雅关闭模拟环境
    const envStatusRes = await getEnvStatus({ simulation_id: currentDecisionId.value })
    
    if (envStatusRes.success && envStatusRes.data?.env_alive) {
      addLog(t('log.closingSimEnv'))
      try {
        await closeSimulationEnv({ 
          simulation_id: currentDecisionId.value,
          timeout: 10
        })
        addLog(t('log.simEnvClosed'))
      } catch (closeErr) {
        addLog(t('log.closeSimEnvFailed'))
        try {
          await stopSimulation({ simulation_id: currentDecisionId.value })
          addLog(t('log.simForceStopSuccess'))
        } catch (stopErr) {
          addLog(t('log.forceStopFailed', { error: stopErr.message }))
        }
      }
    } else {
      // 环境未运行，检查是否需要停止进程
      if (isSimulating.value) {
        addLog(t('log.stoppingSimProcess'))
        try {
          await stopSimulation({ simulation_id: currentDecisionId.value })
          addLog(t('log.simStopped'))
        } catch (err) {
          addLog(t('log.stopSimFailed', { error: err.message }))
        }
      }
    }
  } catch (err) {
    addLog(t('log.checkStatusFailed', { error: err.message }))
  }
  
  // 返回到 Step 2 (环境搭建)
  router.push(taskRoute(2, currentDecisionId.value))
}

const handleNextStep = () => {
  // Step3Simulation 组件会直接处理报告生成和路由跳转
  // 这个方法仅作为备用
  addLog(t('log.enterStep4'))
}

// --- Data Logic ---
const loadSimulationData = async () => {
  try {
    addLog(t('log.loadingSimData', { id: currentDecisionId.value }))

    try {
      const ctx = await resolveSimContext(currentDecisionId.value)
      if (ctx?.simId) resolvedSimulationId.value = ctx.simId
      touchWorkflowStep(3, {
        decisionId: currentDecisionId.value,
        simulationId: resolvedSimulationId.value || undefined,
        ontologyId: ctx?.detail?.ontology_id,
      })
    } catch (_) {
      /* resolve 失败不阻断 */
    }
    
    // 获取 simulation 信息
    const simRes = await getSimulation(currentDecisionId.value)
    if (simRes.success && simRes.data) {
      const simData = simRes.data
      
      // 获取 simulation config 以获取 minutes_per_round
      try {
        const configRes = await getSimulationConfig(currentDecisionId.value)
        if (configRes.success && configRes.data?.time_config?.minutes_per_round) {
          minutesPerRound.value = configRes.data.time_config.minutes_per_round
          addLog(t('log.timeConfig', { minutes: minutesPerRound.value }))
        }
      } catch (configErr) {
        addLog(t('log.timeConfigFetchFailed', { minutes: minutesPerRound.value }))
      }
      
      // 获取 project 信息
      const oid = simData.project_id || simData.ontology_id
      if (oid) {
        const projRes = await getProject(oid)
        if (projRes.success && projRes.data) {
          projectData.value = { ...projRes.data, project_id: projRes.data.id || projRes.data.project_id, ontology: projRes.data.ontology || projRes.data.schema, schema: projRes.data.schema || projRes.data.ontology }
          addLog(t('log.projectLoadSuccess', { id: projRes.data.project_id }))
          
          // 获取 graph 数据
          await loadGraph(projRes.data.graph_id)
        }
      }
    } else {
      addLog(t('log.loadSimDataFailed', { error: simRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('log.loadException', { error: err.message }))
  }
}

const loadGraph = async (_graphId) => {
  const ontologyId = projectData.value?.id || projectData.value?.project_id || projectData.value?.ontology_id
  if (!ontologyId) return
  graphLoading.value = true
  try {
    const res = await getOntologyGraph(ontologyId)
    if (res.success) {
      graphData.value = res.data
      addLog(t('log.graphDataLoadSuccess'))
    } else {
      addLog(t('log.graphDataLoadFailed', { error: res.error || t('common.unknownError') }))
    }
  } catch (e) {
    addLog(t('log.graphDataLoadException', { error: e.message }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = async ({ sync = true } = {}) => {
  const ontologyId = projectData.value?.id || projectData.value?.project_id || projectData.value?.ontology_id
  if (!ontologyId && !projectData.value?.graph_id) return
  if (sync && ontologyId) {
    addLog(t('log.graphSyncRefresh'))
    graphLoading.value = true
    try {
      await snapshotOntology(ontologyId).catch(() => null)
      await loadGraph(projectData.value?.graph_id)
    } finally {
      graphLoading.value = false
    }
    return
  }
  await loadGraph(projectData.value?.graph_id)
}

// --- Auto Refresh Logic（decision SSE 事件驱动，失败降级定时器）---
let graphRefreshTimer = null
let decisionGraphSse = null
let lastGraphRefreshAt = 0
const GRAPH_REFRESH_MIN_MS = 15000

const maybeRefreshGraph = (force = false) => {
  const now = Date.now()
  if (!force && now - lastGraphRefreshAt < GRAPH_REFRESH_MIN_MS) return
  lastGraphRefreshAt = now
  // 自动刷新只读本地快照，不 POST snapshot（避免打爆 Zep）
  refreshGraph({ sync: false })
}

const startGraphRefresh = () => {
  if (decisionGraphSse || graphRefreshTimer) return
  addLog(t('log.graphRealtimeRefreshStart'))
  maybeRefreshGraph(true)

  const id = currentDecisionId.value
  if (!id) {
    graphRefreshTimer = setInterval(() => maybeRefreshGraph(true), 30000)
    return
  }

  decisionGraphSse = subscribeDecision(id, {
    onEvent: () => maybeRefreshGraph(),
    onDone: () => {
      maybeRefreshGraph(true)
      decisionGraphSse = null
      // 推演若仍在跑，降级定时刷新；真正结束后再停
      if (isSimulating.value) {
        if (!graphRefreshTimer) {
          graphRefreshTimer = setInterval(() => maybeRefreshGraph(true), 30000)
        }
      } else {
        stopGraphRefresh()
      }
    },
    onError: (err) => {
      console.warn('[SandOwl] decision graph SSE error, fallback timer', err)
      if (decisionGraphSse) {
        try {
          decisionGraphSse.close()
        } catch (_) {
          /* ignore */
        }
        decisionGraphSse = null
      }
      if (!graphRefreshTimer) {
        graphRefreshTimer = setInterval(() => maybeRefreshGraph(true), 30000)
      }
    },
  })
}

const stopGraphRefresh = () => {
  if (graphRefreshTimer) {
    clearInterval(graphRefreshTimer)
    graphRefreshTimer = null
  }
  if (decisionGraphSse) {
    try {
      decisionGraphSse.close()
    } catch (_) {
      /* ignore */
    }
    decisionGraphSse = null
    addLog(t('log.graphRealtimeRefreshStop'))
  }
}

watch(isSimulating, (newValue) => {
  if (newValue) {
    startGraphRefresh()
  } else {
    stopGraphRefresh()
  }
}, { immediate: true })

onMounted(() => {
  addLog(t('log.simRunViewInit'))
  
  // 记录 maxRounds 配置（值已在初始化时从 query 参数获取）
  if (maxRounds.value) {
    addLog(t('log.customRounds', { rounds: maxRounds.value }))
  }
  
  loadSimulationData()
})

watch(
  () => route.params.decisionId,
  (newId, oldId) => {
    if (!newId || newId === oldId || newId === currentDecisionId.value) return
    currentDecisionId.value = newId
    resolvedSimulationId.value = ''
    projectData.value = null
    graphData.value = null
    stopGraphRefresh()
    loadSimulationData()
  },
)

onUnmounted(() => {
  stopGraphRefresh()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
  font-family: var(--font-sans);
}




.view-switcher {
  display: flex;
  background: #F5F5F5;
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.switch-btn.active {
  background: #FFF;
  color: #000;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}


.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}

.step-name {
  font-weight: 700;
  color: #000;
}

.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
}

.status-indicator.processing .dot { background: #FF5722; animation: pulse 1s infinite; }
.status-indicator.completed .dot { background: #4CAF50; }
.status-indicator.error .dot { background: #F44336; }

@keyframes pulse { 50% { opacity: 0.5; } }

/* Content */
.content-area {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease, transform 0.3s ease;
  will-change: width, opacity, transform;
}

.panel-wrapper.left {
  border-right: 1px solid #EAEAEA;
}
</style>

