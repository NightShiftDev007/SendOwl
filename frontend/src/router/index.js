import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import MainView from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import { resolveDecisionId, taskRoute } from '../utils/taskRoute'

/**
 * 统一任务路由：
 *   /tasks/:decisionId/{graph|environment|simulation|report|interaction}
 * 旧 /process|/simulation|/report|/interaction|/decision|/ontology 兼容重定向。
 */

function legacyRedirect(step, paramKey) {
  return async (to) => {
    const rawId = to.params[paramKey]
    if (rawId === 'new' && step === 1) {
      return { ...taskRoute(1, 'new'), replace: true }
    }
    const decisionId = await resolveDecisionId(rawId)
    if (!decisionId) {
      return {
        name: 'Home',
        query: { error: 'unresolved_task', from: String(rawId || '') },
        replace: true,
      }
    }
    return { ...taskRoute(step, decisionId), replace: true }
  }
}

const routes = [
  { path: '/', name: 'Home', component: Home },

  {
    path: '/tasks/:decisionId',
    redirect: (to) => ({
      name: 'TaskGraph',
      params: { decisionId: to.params.decisionId },
    }),
  },
  {
    path: '/tasks/:decisionId/graph',
    name: 'TaskGraph',
    component: MainView,
    props: true,
  },
  {
    path: '/tasks/:decisionId/environment',
    name: 'TaskEnvironment',
    component: SimulationView,
    props: true,
  },
  {
    path: '/tasks/:decisionId/simulation',
    name: 'TaskSimulation',
    component: SimulationRunView,
    props: true,
  },
  {
    path: '/tasks/:decisionId/report',
    name: 'TaskReport',
    component: ReportView,
    props: true,
  },
  {
    path: '/tasks/:decisionId/interaction',
    name: 'TaskInteraction',
    component: InteractionView,
    props: true,
  },

  // —— 旧路由兼容（只迁移，不生成）——
  {
    path: '/process/:projectId',
    name: 'Process',
    redirect: legacyRedirect(1, 'projectId'),
  },
  {
    path: '/ontology/:ontologyId',
    redirect: legacyRedirect(1, 'ontologyId'),
  },
  { path: '/ontology', redirect: '/' },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    redirect: legacyRedirect(3, 'simulationId'),
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    redirect: legacyRedirect(2, 'simulationId'),
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    redirect: legacyRedirect(4, 'reportId'),
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    redirect: legacyRedirect(5, 'reportId'),
  },

  { path: '/decision/new', redirect: '/' },
  {
    path: '/decision/:id/monitor',
    redirect: legacyRedirect(3, 'id'),
  },
  {
    path: '/decision/:id/compare',
    redirect: legacyRedirect(4, 'id'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
