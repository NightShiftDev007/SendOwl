import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import MainView from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

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

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
