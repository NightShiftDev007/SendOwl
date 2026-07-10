import { createRouter, createWebHistory } from 'vue-router'
import OntologyView from '../views/OntologyView.vue'
import DecisionCreateView from '../views/DecisionCreateView.vue'
import DecisionMonitorView from '../views/DecisionMonitorView.vue'
import CompareView from '../views/CompareView.vue'
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/ontology', name: 'ontology', component: OntologyView },
    { path: '/decision/new', name: 'decision-create', component: DecisionCreateView },
    { path: '/decision/:id/monitor', name: 'decision-monitor', component: DecisionMonitorView, props: true },
    { path: '/decision/:id/compare', name: 'decision-compare', component: CompareView, props: true },
  ],
})

export default router
