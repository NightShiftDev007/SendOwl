<template>
  <div class="geo-map">
    <div class="geo-head">
      <div class="geo-title">
        <h3 class="mono">地域传播飞线</h3>
        <span class="note">{{ mappingNote || '真实地理：adcode 主键 · 多方案同图叠加' }}</span>
      </div>
      <div class="scenario-legend" v-if="scenarios.length > 1">
        <span
          v-for="(s, i) in scenarios"
          :key="s.scenario_id || i"
          class="legend-item"
        >
          <i class="swatch" :style="{ background: scenarioColor(s, i) }"></i>
          {{ shortName(s, i) }}
        </span>
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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const MUNICIPALITIES = new Set(['110000', '120000', '310000', '500000', '810000', '820000'])
const FALLBACK_COLORS = ['#FF4500', '#2563EB', '#059669', '#D97706', '#7C3AED', '#DB2777']

const props = defineProps({
  scenarios: { type: Array, default: () => [] },
})

const chartEl = ref(null)
/** @type {import('vue').Ref<Array<{adcode:string,name:string,level:string}>>} */
const stack = ref([])
let chart = null
const mapCache = new Map()
/** name → adcode for current registered map */
let nameToAdcode = {}

function scenarioColor(s, i = 0) {
  return s?.color || FALLBACK_COLORS[i % FALLBACK_COLORS.length]
}

function shortName(s, i = 0) {
  const kind = String(s?.scenario_id || s?.kind || '').trim()
  if (kind && !/^(default|custom|scn_)/i.test(kind) && kind.length <= 16) return kind
  const name = String(s?.scenario_name || s?.name || '').trim()
  const head = name.split(/[·•|/｜]/)[0].trim()
  if (!head || head.length > 18) return `方案${i + 1}`
  return head.length > 14 ? `${head.slice(0, 13)}…` : head
}

function geoOf(s) {
  return s?.geo_propagation || {}
}

function rawNodesOf(s) {
  const g = geoOf(s)
  if (Array.isArray(g.nodes) && g.nodes.length) return g.nodes
  return (g.cities || []).map((c) => ({
    adcode: c.adcode || '',
    name: c.name,
    fullname: c.name,
    coord: c.coord,
    value: c.value,
    city_adcode: c.adcode || '',
    province_adcode: c.adcode ? String(c.adcode).slice(0, 2) + '0000' : '',
  }))
}

function rawLinesOf(s) {
  return geoOf(s).lines || []
}

const mappingNote = computed(() => {
  for (const s of props.scenarios) {
    const note = geoOf(s).mapping_note
    if (note) return note
  }
  return ''
})

const hasData = computed(() =>
  props.scenarios.some((s) => rawLinesOf(s).length > 0 || rawNodesOf(s).length > 0),
)

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

/** 单方案在当前下钻视野下的线/点 */
function viewLinesAndNodes(nodes, lines) {
  const nodeIndex = buildNodeIndex(nodes)
  const depth = stack.value.length
  const focus = depth ? stack.value[depth - 1].adcode : ''
  const metaAcc = new Map()

  const merged = new Map()
  for (const line of lines) {
    let a = String(line.from || '')
    let b = String(line.to || '')
    if (!a || !b) continue
    if (!/^\d{6}$/.test(a) || !/^\d{6}$/.test(b)) continue

    const span = line.span || (sameCity(a, b, nodeIndex) ? 'intra_city' : 'cross_city')
    const count = Number(line.count) || 1

    if (depth === 0) {
      if (span === 'intra_city') continue
      a = cityOf(a, nodeIndex)
      b = cityOf(b, nodeIndex)
    } else if (stack.value[0] && MUNICIPALITIES.has(stack.value[0].adcode) && depth === 1) {
      const pac = stack.value[0].adcode
      if (provinceOf(a) !== pac && provinceOf(b) !== pac) continue
      if (!sameCity(a, b, nodeIndex)) {
        a = cityOf(a, nodeIndex)
        b = cityOf(b, nodeIndex)
      }
    } else if (depth === 1) {
      const pac = focus
      if (provinceOf(a) !== pac && provinceOf(b) !== pac) continue
      if (span !== 'intra_city') {
        a = cityOf(a, nodeIndex)
        b = cityOf(b, nodeIndex)
      }
    } else {
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
  if (chart && chart.getDom() !== chartEl.value) {
    chart.off('click', onMapClick)
    chart.dispose()
    chart = null
  }
  if (!chart) {
    chart = echarts.init(chartEl.value)
    chart.on('click', onMapClick)
  }

  const series = []
  let globalMaxCity = 1
  let globalMaxLine = 1
  const layers = props.scenarios.map((s, i) => {
    const { lines, nodes } = viewLinesAndNodes(rawNodesOf(s), rawLinesOf(s))
    globalMaxCity = Math.max(globalMaxCity, ...nodes.map((c) => c.value || 1), 1)
    globalMaxLine = Math.max(globalMaxLine, ...lines.map((l) => l.count || 1), 1)
    return { s, i, lines, nodes, color: scenarioColor(s, i), label: shortName(s, i) }
  })

  for (const layer of layers) {
    if (!layer.lines.length && !layer.nodes.length) continue
    const curve = 0.18 + (layer.i % 5) * 0.06
    const lineData = layer.lines
      .map((l) => {
        const from = layer.nodes.find((c) => c.adcode === l.from)
        const to = layer.nodes.find((c) => c.adcode === l.to)
        if (!from?.coord || !to?.coord) return null
        return {
          fromName: l.fromName || from.name,
          toName: l.toName || to.name,
          count: l.count,
          scenario: layer.label,
          coords: [from.coord, to.coord],
        }
      })
      .filter(Boolean)

    series.push({
      name: layer.label,
      type: 'lines',
      coordinateSystem: 'geo',
      zlevel: 2 + layer.i,
      effect: {
        show: true,
        period: 4 + layer.i * 0.4,
        trailLength: 0.3,
        symbol: 'arrow',
        symbolSize: 4,
      },
      lineStyle: {
        color: layer.color,
        width: 1.2,
        opacity: 0.7,
        curveness: curve,
      },
      data: lineData.map((d) => ({
        ...d,
        lineStyle: {
          width: 1 + (2.5 * (d.count || 1)) / globalMaxLine,
          color: layer.color,
          opacity: 0.5 + (0.35 * (d.count || 1)) / globalMaxLine,
          curveness: curve,
        },
      })),
    })

    series.push({
      name: `${layer.label}·点`,
      type: 'effectScatter',
      coordinateSystem: 'geo',
      zlevel: 20 + layer.i,
      legendHoverLink: false,
      rippleEffect: { brushType: 'stroke', scale: 2.5 },
      symbolSize: (val) => 6 + (14 * (val[2] || 1)) / globalMaxCity,
      itemStyle: { color: layer.color, shadowBlur: 6, shadowColor: layer.color },
      data: layer.nodes.map((c) => ({
        name: c.name,
        adcode: c.adcode,
        scenario: layer.label,
        value: [...(c.coord || [0, 0]), c.value || 1],
      })),
    })
  }

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
      legend: {
        show: false,
      },
      tooltip: {
        trigger: 'item',
        formatter: (p) => {
          if (p.seriesType === 'lines') {
            const d = p.data || {}
            const sc = d.scenario ? `<br/><span style="color:#666">${d.scenario}</span>` : ''
            return `${d.fromName || ''} → ${d.toName || ''}<br/>传播 ${d.count || 1} 次${sc}`
          }
          if (p.seriesType === 'effectScatter' || p.seriesType === 'scatter') {
            const v = Array.isArray(p.value) ? p.value[2] : p.value
            const sc = p.data?.scenario ? `<br/><span style="color:#666">${p.data.scenario}</span>` : ''
            return `${p.name}<br/>活跃 ${v || 0}${sc}`
          }
          return p.name
        },
      },
      geo: geoOpt,
      series,
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
  () => props.scenarios,
  async () => {
    stack.value = []
    const spec = await ensureMap()
    await nextTick()
    if (spec) render()
  },
  { deep: true },
)

onMounted(async () => {
  const spec = await ensureMap()
  await nextTick()
  if (spec) render()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chart?.off('click', onMapClick)
  chart?.dispose()
  chart = null
})

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

/** 导出：全国叠加视图截一张即可 */
async function captureAllMaps(pixelRatio = 2) {
  const prevStack = [...stack.value]
  stack.value = []
  await nextTick()
  const spec = await ensureMap()
  if (spec) render()
  await wait(280)
  const results = []
  if (chart && hasData.value) {
    try {
      chart.resize()
      const dataUrl = chart.getDataURL({
        type: 'png',
        pixelRatio,
        backgroundColor: '#ffffff',
      })
      if (dataUrl) {
        results.push({
          index: 0,
          name: props.scenarios.length > 1 ? '全方案叠加' : shortName(props.scenarios[0], 0),
          dataUrl,
        })
      }
    } catch (e) {
      console.warn('[geo-map] capture failed', e)
    }
  }
  stack.value = prevStack
  await nextTick()
  const spec2 = await ensureMap()
  if (spec2) render()
  return results
}

defineExpose({ captureAllMaps })
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
}
.geo-title h3 {
  margin: 0;
  font-size: 13px;
}
.note {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--ink-muted);
}
.scenario-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-muted);
  font-family: var(--font-mono);
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin: 8px 0 4px;
  font-size: 12px;
}
.crumb {
  border: none;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
  padding: 0 2px;
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
