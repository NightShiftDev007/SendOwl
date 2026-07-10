import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import MainView from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

/**
 * 终局：唯一五步流程
 *   / → /process/:id → /simulation/:id → /start → /report/:id → /interaction/:id
 * 旧 /decision/* 路由重定向进五步
 */
const routes = [
  { path: '/', name: 'Home', component: Home },

  {
    path: '/process/:projectId',
    name: 'Process',
    component: MainView,
    props: true,
  },
  {
    path: '/ontology/:ontologyId',
    redirect: (to) => ({
      name: 'Process',
      params: { projectId: to.params.ontologyId },
    }),
  },
  { path: '/ontology', redirect: '/' },

  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true,
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true,
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true,
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true,
  },

  // 旧决策入口退役 → 五步
  { path: '/decision/new', redirect: '/' },
  {
    path: '/decision/:id/monitor',
    redirect: (to) => ({
      name: 'SimulationRun',
      params: { simulationId: to.params.id },
    }),
  },
  {
    path: '/decision/:id/compare',
    redirect: (to) => ({
      name: 'Report',
      params: { reportId: to.params.id },
    }),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
