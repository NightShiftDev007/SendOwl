/**
 * 将预测报告导出为单个 Markdown 文件。
 * 图表 / 地图以 data URI 内嵌，无需配套图片目录。
 */

function escapeCell(v) {
  return String(v ?? '-').replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

function num(v) {
  if (v == null) return null
  if (typeof v === 'object' && 'mean' in v) return Number(v.mean)
  return Number(v)
}

function stdOf(v) {
  if (v == null || typeof v !== 'object' || !('std' in v)) return null
  return Number(v.std)
}

function fmtWithStd(v) {
  const n = num(v)
  if (n == null || Number.isNaN(n)) return '-'
  const s = stdOf(v)
  const base = n.toFixed(1)
  if (s == null || Number.isNaN(s) || s === 0) return base
  return `${base}±${s.toFixed(1)}`
}

function pctWithStd(v) {
  const n = num(v)
  if (n == null || Number.isNaN(n)) return '-'
  const s = stdOf(v)
  const base = `${(n * 100).toFixed(0)}%`
  if (s == null || Number.isNaN(s) || s === 0) return base
  return `${base}±${(s * 100).toFixed(0)}pt`
}

function scenarioShort(s, i) {
  const kind = String(s?.scenario_id || s?.kind || '').trim()
  if (kind && !/^(default|custom|scn_)/i.test(kind) && kind.length <= 16) return kind
  const name = String(s?.scenario_name || s?.name || '').trim()
  const head = name.split(/[·•|/｜]/)[0].trim()
  if (!head || head.length > 18) return `方案${i + 1}`
  return head.length > 12 ? `${head.slice(0, 11)}…` : head
}

function buildCompareMd(compare, images) {
  if (!compare) return ''
  const lines = []
  const scenarios = compare.scenarios || compare.items || []
  lines.push('## 方案对比')
  lines.push('')

  if (scenarios.length) {
    const ranked = scenarios
      .map((s, i) => ({
        label: scenarioShort(s, i),
        opposing: num(s.summary?.stance_share?.opposing),
        actions: num(s.summary?.total_actions),
      }))
      .filter((s) => s.opposing != null && !Number.isNaN(s.opposing))
      .sort((a, b) => a.opposing - b.opposing)
    if (ranked.length) {
      const best = ranked[0]
      lines.push('### 结论')
      lines.push('')
      lines.push(
        `**${best.label}** — 反对率最低（${(best.opposing * 100).toFixed(0)}%），互动 ${best.actions == null || Number.isNaN(best.actions) ? '-' : best.actions.toFixed(1)}`,
      )
      lines.push('')
    }

    lines.push('### 指标汇总')
    lines.push('')
    lines.push('| 方案 | 互动 | 反对 | 级联 | 采样 |')
    lines.push('| --- | --- | --- | --- | --- |')
    for (let i = 0; i < scenarios.length; i++) {
      const s = scenarios[i]
      const full = s.scenario_name || s.name || scenarioShort(s, i)
      lines.push(
        `| ${escapeCell(full)} | ${escapeCell(fmtWithStd(s.summary?.total_actions))} | ${escapeCell(pctWithStd(s.summary?.stance_share?.opposing))} | ${escapeCell(fmtWithStd(s.summary?.max_cascade_depth))} | ${escapeCell(s.sample_count || 1)} |`,
      )
    }
    lines.push('')

    for (let i = 0; i < scenarios.length; i++) {
      const s = scenarios[i]
      if (s.narrative) {
        lines.push(`> **${scenarioShort(s, i)}**：${String(s.narrative).replace(/\n/g, ' ')}`)
        lines.push('')
      }
    }
  }

  for (const img of images || []) {
    if (!img?.dataUrl) continue
    lines.push(`### ${img.title}`)
    lines.push('')
    lines.push(`![${img.title}](${img.dataUrl})`)
    lines.push('')
  }

  const bodyMd =
    compare?.report?.markdown || compare?.narrative || compare?.markdown || ''
  if (bodyMd && typeof bodyMd === 'string' && bodyMd.trim()) {
    lines.push('### 对比报告正文')
    lines.push('')
    lines.push(bodyMd.trim())
    lines.push('')
  }

  return lines.join('\n')
}

function downloadTextFile(filename, text, mime = 'text/markdown;charset=utf-8') {
  const blob = new Blob([text], { type: mime })
  const a = document.createElement('a')
  const url = URL.createObjectURL(blob)
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * @param {object} opts
 * @param {string} opts.title
 * @param {string} [opts.summary]
 * @param {string} [opts.reportId]
 * @param {object|null} [opts.compare]
 * @param {Array<{title:string, content:string}>} [opts.sections]
 * @param {Array<{key:string, title:string, dataUrl:string}>} [opts.images]
 * @param {string} [opts.filenameBase]
 */
export async function exportReportMarkdown(opts) {
  const {
    title = '预测报告',
    summary = '',
    reportId = '',
    compare = null,
    sections = [],
    images = [],
    filenameBase = '预测报告',
  } = opts

  const parts = []
  parts.push(`# ${title}`)
  parts.push('')
  if (summary) {
    parts.push(`> ${String(summary).replace(/\n/g, ' ')}`)
    parts.push('')
  }
  if (reportId) {
    parts.push(`- **报告 ID**：\`${reportId}\``)
    parts.push('')
  }

  const compareMd = buildCompareMd(compare, images)
  if (compareMd) {
    parts.push(compareMd)
  }

  if (sections.length) {
    parts.push('## 报告正文')
    parts.push('')
    sections.forEach((sec, i) => {
      const n = String(i + 1).padStart(2, '0')
      parts.push(`### ${n} ${sec.title || `章节 ${i + 1}`}`)
      parts.push('')
      parts.push((sec.content || '').trim() || '_（暂无内容）_')
      parts.push('')
    })
  }

  const md = `${parts.join('\n').trim()}\n`
  downloadTextFile(`${filenameBase}.md`, md)
}

/** @deprecated 使用 exportReportMarkdown */
export async function exportReportMarkdownZip(opts) {
  return exportReportMarkdown(opts)
}
