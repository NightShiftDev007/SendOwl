<template>
  <main class="page">
    <h1>本体管理</h1>
    <p class="sub">创建常驻本体、上传文档、构建图谱并导出版本快照。</p>

    <div class="grid grid-2">
      <div class="card">
        <h2>创建本体</h2>
        <div class="field">
          <label>名称</label>
          <input v-model="form.name" placeholder="江城市限行新政本体" />
        </div>
        <div class="field">
          <label>模板</label>
          <select v-model="form.template">
            <option value="opinion">舆情/传播</option>
          </select>
        </div>
        <div class="field">
          <label>模拟需求</label>
          <textarea v-model="form.requirement" placeholder="预测不同发布策略下的舆论传播与观点分布" />
        </div>
        <div class="field">
          <label>种子文件（PDF/MD/TXT）</label>
          <input type="file" multiple @change="onFiles" />
        </div>
        <button class="btn primary" :disabled="busy" @click="create">{{ busy ? '创建中…' : '创建并建图' }}</button>
        <p v-if="msg" :class="err ? 'error' : 'success'">{{ msg }}</p>
      </div>

      <div class="card">
        <h2>本体列表</h2>
        <table>
          <thead><tr><th>名称</th><th>状态</th><th>版本</th><th></th></tr></thead>
          <tbody>
            <tr v-for="o in ontologies" :key="o.id">
              <td>{{ o.name }}</td>
              <td><span class="badge" :class="statusClass(o.status)">{{ o.status }}</span></td>
              <td>{{ o.latest_version || '-' }}</td>
              <td class="row">
                <button class="btn" @click="select(o)">查看</button>
                <button class="btn" @click="doSnapshot(o)" :disabled="busy">快照</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!ontologies.length" class="muted">暂无本体</p>
      </div>
    </div>

    <div v-if="selected" class="card" style="margin-top:16px">
      <h2>{{ selected.name }} · 图谱</h2>
      <p class="muted">id={{ selected.id }} · graph={{ selected.graph_id || '-' }}</p>
      <GraphPanel :nodes="graph.nodes" :edges="graph.edges" />
    </div>
  </main>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import GraphPanel from '../components/GraphPanel.vue'
import {
  listOntologies, createOntology, buildOntology, buildStatus,
  snapshotOntology, getOntologyGraph, getOntology,
} from '../api/client'

const ontologies = ref([])
const selected = ref(null)
const graph = reactive({ nodes: [], edges: [] })
const form = reactive({
  name: '江城市限行新政本体',
  template: 'opinion',
  requirement: '预测江城市电动自行车限行新政在不同发布策略下的舆论传播路径、观点分布与关键引爆点。',
  files: [],
})
const busy = ref(false)
const msg = ref('')
const err = ref(false)

function statusClass(s) {
  if (s === 'ready') return 'ok'
  if (s === 'failed') return 'err'
  if (s === 'building') return 'warn'
  return ''
}

function onFiles(e) {
  form.files = Array.from(e.target.files || [])
}

async function refresh() {
  const res = await listOntologies()
  ontologies.value = res.data || res.ontologies || res || []
  if (!Array.isArray(ontologies.value)) ontologies.value = ontologies.value.items || []
}

async function create() {
  busy.value = true; err.value = false; msg.value = ''
  try {
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('template', form.template)
    fd.append('simulation_requirement', form.requirement)
    for (const f of form.files) fd.append('files', f)
    const created = await createOntology(fd)
    const ontology = created.data || created
    const oid = ontology.id || ontology.ontology_id
    msg.value = `已创建 ${oid}，开始建图…`
    const build = await buildOntology(oid, { use_existing_schema: true })
    const taskId = (build.data || build).task_id
    if (taskId) {
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 3000))
        const st = await buildStatus(oid, taskId)
        const d = st.data || st
        msg.value = `建图中… ${d.status || ''} ${d.progress || ''}`
        if (['completed', 'success', 'ready', 'failed', 'error'].includes(d.status)) break
      }
    }
    try { await snapshotOntology(oid) } catch (_) {}
    msg.value = '本体就绪'
    await refresh()
    const detail = await getOntology(oid)
    await select(detail.data || detail)
  } catch (e) {
    err.value = true
    msg.value = e.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function select(o) {
  selected.value = o
  try {
    const g = await getOntologyGraph(o.id)
    const data = g.data || g
    graph.nodes = data.nodes || []
    graph.edges = data.edges || []
  } catch (_) {
    graph.nodes = []; graph.edges = []
  }
}

async function doSnapshot(o) {
  busy.value = true
  try {
    await snapshotOntology(o.id)
    await refresh()
    msg.value = '快照完成'
  } catch (e) {
    err.value = true
    msg.value = e.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>
