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
          :current-step="4"
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
          :currentPhase="4"
          :isSimulating="false"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <!-- Right Panel: Step4 报告生成 -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step4Report
          :decisionId="currentDecisionId"
          :reportId="resolvedReportId"
          :simulationId="resolvedSimulationId"
          :systemLogs="systemLogs"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppHeader from '../components/AppHeader.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step4Report from '../components/Step4Report.vue'
import StepNav from '../components/StepNav.vue'
import { getProject, getOntologyGraph } from '../api/graph'
import { getSimulation, resolveSimContext } from '../api/simulation'
import { getReport, resolveReportId } from '../api/report'
import { touchWorkflowStep } from '../store/workflowContext'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const props = defineProps({
  decisionId: String,
})

const viewMode = ref('workbench')

const currentDecisionId = ref(props.decisionId || route.params.decisionId)
const resolvedReportId = ref('')
const resolvedSimulationId = ref('')
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const systemLogs = ref([])
const currentStatus = ref('processing')

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

const statusClass = computed(() => currentStatus.value)

const statusText = computed(() => {
  if (currentStatus.value === 'error') return 'Error'
  if (currentStatus.value === 'completed') return 'Completed'
  return 'Generating'
})

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

const toggleMaximize = (target) => {
  if (viewMode.value === target) {
    viewMode.value = 'split'
  } else {
    viewMode.value = target
  }
}

const loadReportData = async () => {
  try {
    const decisionId = currentDecisionId.value
    addLog(t('log.loadReportData', { id: decisionId }))

    try {
      const ctx = await resolveSimContext(decisionId)
      if (ctx?.simId) resolvedSimulationId.value = ctx.simId
    } catch (_) {
      /* ignore */
    }

    let rid = ''
    try {
      rid = (await resolveReportId(decisionId)) || ''
    } catch (_) {
      rid = ''
    }
    // 对比模式：无真实 report_* 时用 decisionId 拉 compare 报告
    resolvedReportId.value = rid || decisionId

    const reportRes = await getReport(resolvedReportId.value)
    if (reportRes.success && reportRes.data) {
      const reportData = reportRes.data
      if (reportData.simulation_id && String(reportData.simulation_id).startsWith('sim_')) {
        resolvedSimulationId.value = reportData.simulation_id
      }

      touchWorkflowStep(4, {
        decisionId,
        simulationId: resolvedSimulationId.value || undefined,
        reportId: rid && String(rid).startsWith('report_') ? rid : undefined,
      })

      const lookupId = resolvedSimulationId.value || decisionId
      const simRes = await getSimulation(lookupId)
      if (simRes.success && simRes.data) {
        const simData = simRes.data
        const oid = simData.project_id || simData.ontology_id
        if (oid) {
          const projRes = await getProject(oid)
          if (projRes.success && projRes.data) {
            projectData.value = {
              ...projRes.data,
              project_id: projRes.data.id || projRes.data.project_id,
              ontology: projRes.data.ontology || projRes.data.schema,
              schema: projRes.data.schema || projRes.data.ontology,
            }
            addLog(t('log.projectLoadSuccess', { id: projRes.data.project_id }))
            if (projRes.data.graph_id) {
              await loadGraph(projRes.data.graph_id)
            }
          }
        }
      }
    } else {
      addLog(t('log.getReportInfoFailed', { error: reportRes.error || t('common.unknownError') }))
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

const refreshGraph = () => {
  if (projectData.value?.id || projectData.value?.project_id || projectData.value?.graph_id) {
    loadGraph(projectData.value.graph_id)
  }
}

watch(() => route.params.decisionId, (newId) => {
  if (newId && newId !== currentDecisionId.value) {
    currentDecisionId.value = newId
    loadReportData()
  }
})

onMounted(() => {
  addLog(t('log.reportViewInit'))
  loadReportData()
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

.status-indicator.processing .dot { background: #FF9800; animation: pulse 1s infinite; }
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
