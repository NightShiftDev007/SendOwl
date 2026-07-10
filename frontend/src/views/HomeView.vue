<template>
  <main class="page">
    <h1>AI 决策中心</h1>
    <p class="sub">
      常驻本体 × 多智能体推演 × 多方案对比。先建本体世界，再创建决策任务，并行推演干预方案并量化对比。
    </p>
    <div class="grid grid-3">
      <div class="card">
        <h2>1. 本体管理</h2>
        <p class="muted">上传种子材料，构建可版本化的舆情本体快照。</p>
        <RouterLink class="btn primary" to="/ontology">进入</RouterLink>
      </div>
      <div class="card">
        <h2>2. 创建决策</h2>
        <p class="muted">选择本体版本，配置强硬/柔性/Baseline 等干预方案。</p>
        <RouterLink class="btn primary" to="/decision/new">创建</RouterLink>
      </div>
      <div class="card">
        <h2>3. 对比面板</h2>
        <p class="muted">传播规模、观点结构、关键节点并排对比。</p>
        <p class="muted" style="margin-top:12px">从决策监控页进入对比。</p>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <h2>后端状态</h2>
      <p class="muted">{{ healthText }}</p>
    </div>

    <div class="card" style="margin-top:16px" v-if="decisions.length">
      <h2>最近决策</h2>
      <table>
        <thead><tr><th>标题</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="d in decisions" :key="d.id">
            <td>{{ d.title }}</td>
            <td><span class="badge">{{ d.status }}</span></td>
            <td class="row">
              <RouterLink class="btn" :to="`/decision/${d.id}/monitor`">监控</RouterLink>
              <RouterLink class="btn primary" :to="`/decision/${d.id}/compare`">对比</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { health, listDecisions } from '../api/client'

const healthText = ref('检查中…')
const decisions = ref([])
onMounted(async () => {
  try {
    const h = await health()
    healthText.value = `OK · ${h.service || 'AI Decision Center'}`
  } catch (e) {
    healthText.value = '后端未连接（请先 pnpm run backend）'
  }
  try {
    const res = await listDecisions()
    const list = res.data || res || []
    decisions.value = Array.isArray(list) ? list.slice(0, 8) : []
  } catch (_) {}
})
</script>
