<template>
  <div ref="el" class="graph-panel"></div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
})

const el = ref(null)
let sim = null
let svg = null

function render() {
  if (!el.value) return
  const width = el.value.clientWidth || 640
  const height = 360
  el.value.innerHTML = ''
  svg = d3.select(el.value).append('svg').attr('width', width).attr('height', height)

  const nodes = props.nodes.map((n, i) => ({
    id: n.uuid || n.id || `n${i}`,
    name: n.name || n.label || n.uuid || `n${i}`,
    ...n,
  }))
  const idSet = new Set(nodes.map((n) => n.id))
  const links = (props.edges || [])
    .map((e, i) => ({
      source: e.source_node_uuid || e.source || e.from,
      target: e.target_node_uuid || e.target || e.to,
      name: e.name || e.edge_type || '',
      i,
    }))
    .filter((e) => idSet.has(e.source) && idSet.has(e.target))

  if (!nodes.length) {
    svg.append('text').attr('x', 20).attr('y', 40).attr('fill', '#8b9bb4').text('暂无图谱数据')
    return
  }

  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id((d) => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-180))
    .force('center', d3.forceCenter(width / 2, height / 2))

  const link = svg.append('g').selectAll('line').data(links).enter().append('line')
    .attr('stroke', '#2d3a4f').attr('stroke-width', 1.2)

  const node = svg.append('g').selectAll('g').data(nodes).enter().append('g').call(
    d3.drag()
      .on('start', (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
  )

  node.append('circle').attr('r', 7).attr('fill', '#3b82f6').attr('stroke', '#93c5fd')
  node.append('text').text((d) => d.name).attr('x', 10).attr('y', 4)
    .attr('fill', '#cbd5e1').attr('font-size', 11)

  sim.on('tick', () => {
    link
      .attr('x1', (d) => d.source.x).attr('y1', (d) => d.source.y)
      .attr('x2', (d) => d.target.x).attr('y2', (d) => d.target.y)
    node.attr('transform', (d) => `translate(${d.x},${d.y})`)
  })
}

onMounted(render)
watch(() => [props.nodes, props.edges], render, { deep: true })
onBeforeUnmount(() => { if (sim) sim.stop() })
</script>

<style scoped>
.graph-panel { width: 100%; min-height: 360px; background: #121a26; border-radius: 10px; overflow: hidden; }
</style>
