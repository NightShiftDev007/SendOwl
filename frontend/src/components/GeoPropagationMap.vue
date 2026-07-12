<template>
  <div class="geo-map">
    <div class="geo-head">
      <div class="geo-title">
        <h3 class="mono">地域传播飞线</h3>
        <span class="note">{{ mappingNote || '真实地理：adcode 主键' }}</span>
      </div>
      <div class="scenario-tabs" v-if="scenarios.length">
        <button
          v-for="(s, i) in scenarios"
          :key="s.scenario_id || i"
          type="button"
          class="tab"
          :class="{ active: i === activeIndex }"
          :style="i === activeIndex ? { borderColor: s.color || 'var(--brand)', color: s.color || 'var(--brand)' } : {}"
          @click="activeIndex = i"
        >
          {{ shortName(s) }}
        </button>
      </div>
    </div>

    <div class="breadcrumb" v-if="hasData">
      <button type="button" class="crumb" :class="{ active: stack.length === 0 }" @click="goNation">
        全国
      </button>
      <template v-for="(item, idx) in stack" :key="item.adcode">
        <span class="sep">/</span>
        <button
          type="button"
          class="crumb"
          :class="{ active: idx === stack.length - 1 }"
          @click="goStack(idx)"
        >
          {{ item.name || item.adcode }}
        </button>
      </template>
      <span class="hint mono" v-if="stack.length === 0">点击省份下钻</span>
    </div>

    <div v-if="!hasData" class="empty">
      暂无城际传播边（需有转发 / 引用 / 评论等动作）
    </div>
    <div v-else ref="chartEl" class="chart"></div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const MUNICIPALITIES = new Set(['110000', '120000', '310000', '500000', '810000', '820000'])

const props = defineProps({
  scenarios: { type: Array, default: () => [] },
})

const chartEl = ref(null)
const activeIndex = ref(0)
/** @type {import('vue').Ref<Array<{adcode:string,name:string,level:string}>>} */
const stack = ref([])
let chart = null
const mapCache = new Map()
/** name → adcode for current registered map */
let nameToAdcode = {}

const active = computed(() => props.scenarios[activeIndex.value] || null)
const geo = computed(() => active.value?.geo_propagation || {})
const mappingNote = computed(() => geo.value.mapping_note || '')
const rawNodes = computed(() => {
  const g = geo.value
  if (Array.isArray(g.nodes) && g.nodes.length) return g.nodes
  // 兼容旧 cities
  return (g.cities || []).map((c) => ({
    adcode: c.adcode || '',
    name: c.name,
    fullname: c.name,
    coord: c.coord,
    value: c.value,
    city_adcode: c.adcode || '',
    province_adcode: c.adcode ? String(c.adcode).slice(0, 2) + '0000' : '',
  }))
})
const rawLines = computed(() => geo.value.lines || [])
const hasData = computed(() => {
  return rawLines.value.length > 0 || rawNodes.value.length > 0
})

function shortName(s) {
  const name = String(s.scenario_name || s.name || '')
  return name.split(/[·•]/)[0].trim() || name
}

function provinceOf(code) {
  const c = String(code || '')
  if (c.length < 2) return ''
  return c.slice(0, 2) + '0000'
}

function cityOf(code, nodeIndex) {
  const c = String(code || '')
  if (!c) return ''
  if (MUNICIPALITIES.has(provinceOf(c))) return provinceOf(c)
  const node = nodeIndex.get(c)
  if (node?.city_adcode) return node.city_adcode
  if (c.endsWith('00')) return c
  return c.slice(0, 4) + '00'
}

function sameCity(a, b, nodeIndex) {
  return cityOf(a, nodeIndex) === cityOf(b, nodeIndex)
}

function buildNodeIndex(nodes) {
  const idx = new Map()
  for (const n of nodes) {
    if (n.adcode) idx.set(String(n.adcode), n)
  }
  return idx
}

function ensureMeta(adcode, nodeIndex, metaAcc) {
  const c = String(adcode)
  if (metaAcc.has(c)) return metaAcc.get(c)
  const leaf = nodeIndex.get(c)
  if (leaf?.coord) {
    const m = {
      adcode: c,
      name: leaf.name || leaf.fullname || c,
      fullname: leaf.fullname || leaf.name || c,
      coord: leaf.coord,
      value: leaf.value || 1,
    }
    metaAcc.set(c, m)
    return m
  }
  // 从子节点上卷：找任意同 city/province 的节点坐标
  for (const n of nodeIndex.values()) {
    if (cityOf(n.adcode, nodeIndex) === c || provinceOf(n.adcode) === c) {
      const m = {
        adcode: c,
        name: n.city || n.province || n.name || c,
        fullname: n.city || n.province || n.fullname || c,
        coord: n.coord,
        value: 1,
      }
      metaAcc.set(c, m)
      return m
    }
  }
  return null
}

function viewLinesAndNodes() {
  const nodes = rawNodes.value
  const lines = rawLines.value
  const nodeIndex = buildNodeIndex(nodes)
  const depth = stack.value.length
  const focus = depth ? stack.value[depth - 1].adcode : ''
  const metaAcc = new Map()

  const merged = new Map()
  for (const line of lines) {
    let a = String(line.from || '')
    let b = String(line.to || '')
    if (!a || !b) continue
    // 旧数据：名称主键无法下钻，尽量跳过非数字
    if (!/^\d{6}$/.test(a) || !/^\d{6}$/.test(b)) continue

    const span = line.span || (sameCity(a, b, nodeIndex) ? 'intra_city' : 'cross_city')
    const count = Number(line.count) || 1

    if (depth === 0) {
      if (span === 'intra_city') continue
      a = cityOf(a, nodeIndex)
      b = cityOf(b, nodeIndex)
    } else if (stack.value[0] && MUNICIPALITIES.has(stack.value[0].adcode) && depth === 1) {
      // 直辖：区内飞线用 leaf
      const pac = stack.value[0].adcode
      if (provinceOf(a) !== pac && provinceOf(b) !== pac) continue
      if (!sameCity(a, b, nodeIndex)) {
        // 跨出本市的边：仍显示，端点上卷
        a = cityOf(a, nodeIndex)
        b = cityOf(b, nodeIndex)
      }
    } else if (depth === 1) {
      // 省视图
      const pac = focus
      if (provinceOf(a) !== pac && provinceOf(b) !== pac) continue
      if (span === 'intra_city') {
        // keep leaf
      } else {
        a = cityOf(a, nodeIndex)
        b = cityOf(b, nodeIndex)
      }
    } else {
      // 市视图
      const cac = focus
      if (!sameCity(a, cac, nodeIndex) || !sameCity(b, cac, nodeIndex)) continue
    }

    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    merged.set(key, (merged.get(key) || 0) + count)
  }

  const outLines = []
  const used = new Set()
  for (const [key, count] of merged) {
    const [a, b] = key.split('|')
    const ma = ensureMeta(a, nodeIndex, metaAcc)
    const mb = ensureMeta(b, nodeIndex, metaAcc)
    if (!ma?.coord || !mb?.coord) continue
    outLines.push({ from: a, to: b, count, fromName: ma.name, toName: mb.name })
    used.add(a)
    used.add(b)
  }

  // 活跃点：当前视野相关 nodes
  const outNodes = []
  for (const n of nodes) {
    const code = String(n.adcode || '')
    if (!code) continue
    let include = false
    if (depth === 0) {
      const c = cityOf(code, nodeIndex)
      include = used.has(c)
      if (include) {
        const m = ensureMeta(c, nodeIndex, metaAcc)
        if (m && !outNodes.find((x) => x.adcode === c)) {
          outNodes.push({ ...m, value: (m.value || 1) + (n.value || 0) })
        }
        continue
      }
    } else if (depth === 1 && MUNICIPALITIES.has(focus)) {
      include = provinceOf(code) === focus
    } else if (depth === 1) {
      include = provinceOf(code) === focus
    } else {
      include = sameCity(code, focus, nodeIndex)
    }
    if (include && n.coord) {
      outNodes.push({
        adcode: code,
        name: n.name || n.fullname || code,
        coord: n.coord,
        value: n.value || 1,
      })
      used.add(code)
    }
  }

  // 补齐线端点
  for (const code of used) {
    if (!outNodes.find((x) => x.adcode === code)) {
      const m = ensureMeta(code, nodeIndex, metaAcc)
      if (m) outNodes.push(m)
    }
  }

  return { lines: outLines, nodes: outNodes }
}

async function loadGeoJson(path) {
  if (mapCache.has(path)) return mapCache.get(path)
  const res = await fetch(`/geojson/${path}`)
  if (!res.ok) throw new Error(`map ${path} ${res.status}`)
  const geoJson = await res.json()
  mapCache.set(path, geoJson)
  return geoJson
}

function buildNameMap(geoJson) {
  const map = {}
  for (const f of geoJson.features || []) {
    const pr = f.properties || {}
    const code = pr.code ? String(pr.code) : ''
    if (!code) continue
    if (pr.name) map[pr.name] = code
    if (pr.fullname) map[pr.fullname] = code
  }
  return map
}

function currentMapSpec() {
  const depth = stack.value.length
  if (depth === 0) {
    return { mapName: 'china_nation', path: '100000.json', center: [105, 36], zoom: 1.15 }
  }
  const top = stack.value[0]
  const cur = stack.value[depth - 1]
  if (MUNICIPALITIES.has(top.adcode)) {
    return {
      mapName: `china_${top.adcode}`,
      path: `${top.adcode}.json`,
      center: null,
      zoom: 1.1,
    }
  }
  if (depth === 1) {
    return {
      mapName: `china_${cur.adcode}`,
      path: `${cur.adcode}.json`,
      center: null,
      zoom: 1.05,
    }
  }
  // city
  const pac = top.adcode
  const cac = cur.adcode
  return {
    mapName: `china_${cac}`,
    path: `${pac}/${cac}.json`,
    center: null,
    zoom: 1.05,
  }
}

async function ensureMap() {
  const spec = currentMapSpec()
  try {
    const geoJson = await loadGeoJson(spec.path)
    echarts.registerMap(spec.mapName, geoJson)
    nameToAdcode = buildNameMap(geoJson)
    return spec
  } catch (e) {
    console.warn('load map failed', e)
    if (spec.path !== '100000.json') {
      stack.value = []
      return ensureMap()
    }
    return null
  }
}

function render() {
  if (!chartEl.value || !hasData.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
    chart.on('click', onMapClick)
  }

  const color = active.value?.color || '#FF4500'
  const { lines, nodes } = viewLinesAndNodes()
  const maxCity = Math.max(...nodes.map((c) => c.value || 1), 1)
  const maxLine = Math.max(...lines.map((l) => l.count || 1), 1)

  const scatterData = nodes.map((c) => ({
    name: c.name,
    adcode: c.adcode,
    value: [...(c.coord || [0, 0]), c.value || 1],
  }))

  const lineData = lines
    .map((l) => {
      const from = nodes.find((c) => c.adcode === l.from)
      const to = nodes.find((c) => c.adcode === l.to)
      if (!from?.coord || !to?.coord) return null
      return {
        fromName: l.fromName || from.name,
        toName: l.toName || to.name,
        count: l.count,
        coords: [from.coord, to.coord],
      }
    })
    .filter(Boolean)

  const spec = currentMapSpec()
  const geoOpt = {
    map: spec.mapName,
    roam: true,
    zoom: spec.zoom,
    itemStyle: {
      areaColor: '#f3f4f6',
      borderColor: '#d1d5db',
      borderWidth: 0.8,
    },
    emphasis: {
      itemStyle: { areaColor: '#e5e7eb' },
      label: { show: true, color: '#333', fontSize: 10 },
    },
    label: { show: stack.value.length > 0, fontSize: 9, color: '#666' },
  }
  if (spec.center) geoOpt.center = spec.center

  chart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (p) => {
          if (p.seriesType === 'lines') {
            const d = p.data || {}
            return `${d.fromName || ''} → ${d.toName || ''}<br/>传播 ${d.count || 1} 次`
          }
          if (p.seriesType === 'effectScatter' || p.seriesType === 'scatter') {
            const v = Array.isArray(p.value) ? p.value[2] : p.value
            return `${p.name}<br/>活跃 ${v || 0}`
          }
          return p.name
        },
      },
      geo: geoOpt,
      series: [
        {
          name: '传播飞线',
          type: 'lines',
          coordinateSystem: 'geo',
          zlevel: 2,
          effect: {
            show: true,
            period: 4,
            trailLength: 0.35,
            symbol: 'arrow',
            symbolSize: 5,
          },
          lineStyle: {
            color,
            width: 1.2,
            opacity: 0.65,
            curveness: 0.25,
          },
          data: lineData.map((d) => ({
            ...d,
            lineStyle: {
              width: 1 + (3 * (d.count || 1)) / maxLine,
              color,
              opacity: 0.55 + (0.35 * (d.count || 1)) / maxLine,
              curveness: 0.25,
            },
          })),
        },
        {
          name: '地域活跃',
          type: 'effectScatter',
          coordinateSystem: 'geo',
          zlevel: 3,
          rippleEffect: { brushType: 'stroke', scale: 3 },
          symbolSize: (val) => 8 + (18 * (val[2] || 1)) / maxCity,
          itemStyle: { color, shadowBlur: 8, shadowColor: color },
          data: scatterData,
        },
      ],
    },
    true,
  )
}

async function onMapClick(params) {
  if (params.componentType !== 'geo') return
  const name = params.name
  if (!name) return
  const code = nameToAdcode[name]
  if (!code) return

  const depth = stack.value.length
  if (depth === 0) {
    stack.value = [{ adcode: code, name, level: MUNICIPALITIES.has(code) ? 'muni' : 'province' }]
  } else if (depth === 1 && !MUNICIPALITIES.has(stack.value[0].adcode)) {
    if (code.endsWith('0000')) return
    stack.value = [...stack.value, { adcode: code, name, level: 'city' }]
  } else {
    return
  }
  const spec = await ensureMap()
  if (spec) render()
}

function goNation() {
  stack.value = []
  ensureMap().then((spec) => {
    if (spec) render()
  })
}

function goStack(idx) {
  stack.value = stack.value.slice(0, idx + 1)
  ensureMap().then((spec) => {
    if (spec) render()
  })
}

function resize() {
  chart?.resize()
}

watch(
  () => [props.scenarios, activeIndex.value],
  async () => {
    if (activeIndex.value >= props.scenarios.length) activeIndex.value = 0
    stack.value = []
    const spec = await ensureMap()
    if (spec) render()
  },
  { deep: true },
)

watch(
  stack,
  async () => {
    // stack changes handled in click/go*
  },
)

onMounted(async () => {
  const spec = await ensureMap()
  if (spec) render()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chart?.off('click', onMapClick)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.geo-map {
  border: 1px solid var(--border);
  background: var(--bg);
  margin: 0 14px 12px;
  padding: 10px 12px 8px;
}
.geo-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 6px;
}
.geo-title h3 {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.04em;
}
.note {
  font-size: 11px;
  color: var(--ink-muted);
  line-height: 1.4;
}
.breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  margin-bottom: 8px;
  font-size: 12px;
}
.crumb {
  border: none;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
  padding: 2px 4px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.crumb.active {
  color: var(--ink);
  font-weight: 700;
}
.crumb:hover {
  color: var(--ink);
}
.sep {
  color: var(--ink-muted);
  opacity: 0.5;
}
.hint {
  margin-left: 8px;
  color: var(--ink-muted);
  font-size: 11px;
}
.scenario-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tab {
  border: 1px solid var(--border);
  background: var(--surface, #fff);
  color: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
}
.tab.active {
  font-weight: 700;
  background: var(--bg-muted, #f7f7f7);
}
.chart {
  height: 360px;
  width: 100%;
}
.empty {
  padding: 28px 12px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 13px;
}
.mono {
  font-family: var(--font-mono);
}
</style>
