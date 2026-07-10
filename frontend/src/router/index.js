import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import MainView from '../views/MainView.vue'
import DecisionCreateView from '../views/DecisionCreateView.vue'
import DecisionMonitorView from '../views/DecisionMonitorView.vue'
import DecisionCompareView from '../views/DecisionCompareView.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  {
    path: '/ontology/:ontologyId',
    name: 'OntologyWorkspace',
    component: MainView,
    props: true,
  },
  // 兼容 MiroFish 旧路由
  {
    path: '/process/:projectId',
    redirect: (to) => ({
      name: 'OntologyWorkspace',
      params: { ontologyId: to.params.projectId },
    }),
  },
  {
    path: '/ontology',
    redirect: '/',
  },
  {
    path: '/decision/new',
    name: 'DecisionCreate',
    component: DecisionCreateView,
  },
  {
    path: '/decision/:id/monitor',
    name: 'DecisionMonitor',
    component: DecisionMonitorView,
    props: true,
  },
  {
    path: '/decision/:id/compare',
    name: 'DecisionCompare',
    component: DecisionCompareView,
    props: true,
  },
  // 兼容旧模拟/报告路由 → 决策中心对应页
  {
    path: '/simulation/:simulationId',
    redirect: (to) => ({
      name: 'DecisionMonitor',
      params: { id: to.params.simulationId },
    }),
  },
  {
    path: '/simulation/:simulationId/start',
    redirect: (to) => ({
      name: 'DecisionMonitor',
      params: { id: to.params.simulationId },
    }),
  },
  {
    path: '/report/:reportId',
    redirect: (to) => ({
      name: 'DecisionCompare',
      params: { id: to.params.reportId },
    }),
  },
  {
    path: '/interaction/:reportId',
    redirect: (to) => ({
      name: 'DecisionCompare',
      params: { id: to.params.reportId },
    }),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
