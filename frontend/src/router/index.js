import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import MainView from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'
import { STAGE_TO_STEP, taskRoute } from '../utils/taskRoute'
import {
  getEffectiveMaxReached,
  syncWorkflowFromServer,
} from '../store/workflowContext'

/**
 * 统一任务路由：
 *   /tasks/:decisionId/{graph|environment|simulation|report|interaction}
 */
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
]

/** Vite base 保持 /；仅在经 nginx /SandOwl/ 穿透时用子路径 history */
function routerBase() {
  if (typeof window === 'undefined') return '/'
  const p = window.location.pathname || '/'
  return p === '/SandOwl' || p.startsWith('/SandOwl/') ? '/SandOwl/' : '/'
}

const router = createRouter({
  history: createWebHistory(routerBase()),
  routes,
})

const ROUTE_STEP = {
  TaskGraph: 1,
  TaskEnvironment: 2,
  TaskSimulation: 3,
  TaskReport: 4,
  TaskInteraction: 5,
}

/** 深链/顶栏之外：不可达步骤一律打回当前最大可达步 */
router.beforeEach(async (to) => {
  const decisionId = String(to.params.decisionId || '')
  if (!decisionId || decisionId === 'new' || !decisionId.startsWith('dec_')) {
    return true
  }
  const step =
    ROUTE_STEP[to.name] ||
    STAGE_TO_STEP[String(to.path.split('/').pop() || '')] ||
    0
  if (!step || step <= 2) return true

  await syncWorkflowFromServer(decisionId)
  // 不用 canReachStep：它会把「当前页」始终放行，深链需要严格按 serverMaxReached
  const max = Math.max(1, Math.min(5, getEffectiveMaxReached() || 1))
  if (step <= max) return true
  return taskRoute(max, decisionId)
})

export default router
