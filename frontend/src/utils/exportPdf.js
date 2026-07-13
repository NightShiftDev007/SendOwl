/**
 * 预测报告 PDF：按结构化内容生成固定 A4 文档，走浏览器「打印 → 另存为 PDF」。
 * 正文是真实文字（非页面截图），图表/地图用 ECharts 导出的 PNG 嵌入，避免不同缩放/分辨率导致版式漂移。
 */
import { renderMarkdown } from './markdown'

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
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

function buildCompareHtml(compare, images) {
  if (!compare) return ''
  const scenarios = compare.scenarios || compare.items || []
  const parts = ['<section class="block compare"><h2>方案对比</h2>']

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
      const actions =
        best.actions == null || Number.isNaN(best.actions) ? '-' : best.actions.toFixed(1)
      parts.push(
        `<div class="verdict"><strong>${escapeHtml(best.label)}</strong> — 反对率最低（${(best.opposing * 100).toFixed(0)}%），互动 ${escapeHtml(actions)}</div>`,
      )
    }

    parts.push('<table><thead><tr><th>方案</th><th>互动</th><th>反对</th><th>级联</th><th>采样</th></tr></thead><tbody>')
    for (let i = 0; i < scenarios.length; i++) {
      const s = scenarios[i]
      const full = s.scenario_name || s.name || scenarioShort(s, i)
      const label = String(full).length > 40 ? `${String(full).slice(0, 38)}…` : full
      parts.push(
        `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(fmtWithStd(s.summary?.total_actions))}</td><td>${escapeHtml(pctWithStd(s.summary?.stance_share?.opposing))}</td><td>${escapeHtml(fmtWithStd(s.summary?.max_cascade_depth))}</td><td>${escapeHtml(s.sample_count || 1)}</td></tr>`,
      )
    }
    parts.push('</tbody></table>')

    for (let i = 0; i < scenarios.length; i++) {
      const s = scenarios[i]
      if (s.narrative) {
        const text = String(s.narrative).replace(/\n/g, ' ')
        parts.push(
          `<p class="narrative"><strong>${escapeHtml(scenarioShort(s, i))}</strong>：${escapeHtml(text.length > 160 ? `${text.slice(0, 158)}…` : text)}</p>`,
        )
      }
    }
  }

  const list = images || []
  const pair = list.filter((img) => img.key === 'chart-spread' || img.key === 'chart-stance')
  const rest = list.filter((img) => img.key !== 'chart-spread' && img.key !== 'chart-stance')

  if (pair.length) {
    parts.push('<div class="chart-grid">')
    for (const img of pair) {
      if (!img?.dataUrl) continue
      parts.push(
        `<figure class="chart chart--sm"><figcaption>${escapeHtml(img.title)}</figcaption><img src="${img.dataUrl}" alt="${escapeHtml(img.title)}" /></figure>`,
      )
    }
    parts.push('</div>')
  }

  for (const img of rest) {
    if (!img?.dataUrl) continue
    const cls = img.kind === 'map' ? 'chart chart--map' : 'chart'
    parts.push(
      `<figure class="${cls}"><figcaption>${escapeHtml(img.title)}</figcaption><img src="${img.dataUrl}" alt="${escapeHtml(img.title)}" /></figure>`,
    )
  }

  const bodyMd =
    compare?.report?.markdown || compare?.narrative || compare?.markdown || ''
  if (bodyMd && String(bodyMd).trim()) {
    parts.push('<h3>对比报告正文</h3>')
    parts.push(`<div class="md">${renderMarkdown(String(bodyMd))}</div>`)
  }

  parts.push('</section>')
  return parts.join('\n')
}

/** 缩小 dataURL，控制打印尺寸与文件体积 */
function downscaleDataUrl(dataUrl, maxWidth = 880, quality = 0.82) {
  return new Promise((resolve) => {
    if (!dataUrl) return resolve(null)
    const img = new Image()
    img.onload = () => {
      try {
        const w = img.naturalWidth || img.width
        const h = img.naturalHeight || img.height
        if (!w || !h) return resolve(dataUrl)
        const scale = w > maxWidth ? maxWidth / w : 1
        const cw = Math.max(1, Math.round(w * scale))
        const ch = Math.max(1, Math.round(h * scale))
        const canvas = document.createElement('canvas')
        canvas.width = cw
        canvas.height = ch
        const ctx = canvas.getContext('2d')
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, cw, ch)
        ctx.drawImage(img, 0, 0, cw, ch)
        resolve(canvas.toDataURL('image/jpeg', quality))
      } catch {
        resolve(dataUrl)
      }
    }
    img.onerror = () => resolve(dataUrl)
    img.src = dataUrl
  })
}

async function prepareImages(images) {
  const out = []
  for (const img of images || []) {
    const maxW = img.kind === 'map' ? 860 : 720
    const dataUrl = await downscaleDataUrl(img.dataUrl, maxW, 0.84)
    if (!dataUrl) continue
    out.push({ ...img, dataUrl })
  }
  return out
}

function buildPrintHtml(opts) {
  const {
    title = '预测报告',
    summary = '',
    reportId = '',
    compare = null,
    sections = [],
    images = [],
  } = opts

  const sectionHtml = sections
    .map((sec, i) => {
      const n = String(i + 1).padStart(2, '0')
      const body = sec.content
        ? renderMarkdown(sec.content)
        : '<p class="muted">（暂无内容）</p>'
      return `<section class="block"><h2>${n} ${escapeHtml(sec.title || `章节 ${i + 1}`)}</h2><div class="md">${body}</div></section>`
    })
    .join('\n')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    @page { size: A4; margin: 14mm 12mm; }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      background: #fff;
      color: #111;
      font: 11pt/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .sheet {
      max-width: 186mm;
      margin: 0 auto;
      padding: 8mm 0 12mm;
    }
    .tag {
      display: inline-block;
      background: #111;
      color: #fff;
      font-size: 8.5pt;
      font-weight: 700;
      padding: 2px 6px;
      letter-spacing: 0.04em;
    }
    .meta { color: #6b7280; font-size: 9pt; margin-left: 8px; }
    h1 {
      font-size: 16pt;
      line-height: 1.35;
      margin: 10px 0 8px;
      font-weight: 700;
    }
    .summary {
      margin: 0 0 12px;
      color: #374151;
      font-size: 10.5pt;
      line-height: 1.55;
    }
    hr {
      border: none;
      border-top: 1px solid #e5e7eb;
      margin: 0 0 14px;
    }
    h2 {
      font-size: 12.5pt;
      margin: 0 0 8px;
      padding-bottom: 4px;
      border-bottom: 1px solid #f3f4f6;
    }
    h3 { font-size: 11.5pt; margin: 12px 0 6px; }
    .block { margin-bottom: 14px; }
    .verdict {
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      padding: 8px 10px;
      margin-bottom: 10px;
      font-size: 10.5pt;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 9.5pt;
      margin: 0 0 10px;
    }
    th, td {
      border: 1px solid #e5e7eb;
      padding: 5px 7px;
      text-align: left;
      vertical-align: top;
    }
    th { background: #f9fafb; font-weight: 600; }
    .narrative { font-size: 9.5pt; color: #4b5563; margin: 4px 0; }
    .chart-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px 10px;
      margin: 8px 0 10px;
    }
    figure.chart {
      margin: 8px 0 10px;
      page-break-inside: avoid;
      break-inside: avoid;
      text-align: center;
    }
    figure.chart figcaption {
      font-size: 9pt;
      font-weight: 600;
      margin-bottom: 3px;
      color: #111;
      text-align: left;
    }
    figure.chart img {
      display: block;
      width: auto;
      max-width: 100%;
      max-height: 52mm;
      height: auto;
      margin: 0 auto;
      object-fit: contain;
      border: 1px solid #eee;
    }
    figure.chart--sm img {
      max-height: 42mm;
    }
    figure.chart--map img {
      max-height: 68mm;
      max-width: 92%;
    }
    .md { font-size: 10.5pt; }
    .md h2, .md .md-h2 { font-size: 12pt; margin: 12px 0 6px; }
    .md h3, .md .md-h3 { font-size: 11pt; margin: 10px 0 5px; }
    .md h4, .md .md-h4, .md h5, .md .md-h5 { font-size: 10.5pt; margin: 8px 0 4px; }
    .md p, .md li { margin: 0 0 6px; }
    .md blockquote, .md .md-quote {
      margin: 6px 0;
      padding: 4px 10px;
      border-left: 3px solid #d1d5db;
      color: #4b5563;
    }
    .md table { font-size: 9pt; }
    .muted { color: #9ca3af; }
    .toolbar {
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
      background: #f8fafc;
      border-bottom: 1px solid #e5e7eb;
      font-size: 12px;
    }
    .toolbar button {
      border: 1px solid #d1d5db;
      background: #111;
      color: #fff;
      border-radius: 6px;
      padding: 7px 12px;
      font-weight: 600;
      cursor: pointer;
    }
    .toolbar .hint { color: #6b7280; }
    @media print {
      .toolbar { display: none !important; }
      .sheet { max-width: none; padding: 0; }
    }
  </style>
</head>
<body>
  <div class="toolbar">
    <button type="button" id="print-btn">打印 / 另存为 PDF</button>
    <span class="hint">若未自动弹出打印框，请点左侧按钮；打印机请选「另存为 PDF」</span>
  </div>
  <article class="sheet">
    <div>
      <span class="tag">预测报告</span>
      ${reportId ? `<span class="meta">ID: ${escapeHtml(reportId)}</span>` : ''}
    </div>
    <h1>${escapeHtml(title)}</h1>
    ${summary ? `<p class="summary">${escapeHtml(summary)}</p>` : ''}
    <hr />
    ${buildCompareHtml(compare, images)}
    ${sectionHtml}
  </article>
  <script>
    (function () {
      var btn = document.getElementById('print-btn');
      if (btn) btn.addEventListener('click', function () { window.print(); });

      function waitImages(timeoutMs) {
        var imgs = Array.prototype.slice.call(document.images || []);
        if (!imgs.length) return Promise.resolve();
        return new Promise(function (resolve) {
          var left = imgs.length;
          var done = false;
          function finish() {
            if (done) return;
            done = true;
            resolve();
          }
          var timer = setTimeout(finish, timeoutMs || 4000);
          imgs.forEach(function (img) {
            if (img.complete) {
              if (--left <= 0) { clearTimeout(timer); finish(); }
              return;
            }
            img.onload = img.onerror = function () {
              if (--left <= 0) { clearTimeout(timer); finish(); }
            };
          });
        });
      }

      function tryPrint() {
        try { window.focus(); window.print(); } catch (e) {}
      }

      if (document.readyState === 'complete') {
        waitImages(4000).then(function () { setTimeout(tryPrint, 150); });
      } else {
        window.addEventListener('load', function () {
          waitImages(4000).then(function () { setTimeout(tryPrint, 150); });
        });
      }
    })();
  <\/script>
</body>
</html>`
}

/**
 * @param {object} opts
 * @param {string} opts.title
 * @param {string} [opts.summary]
 * @param {string} [opts.reportId]
 * @param {object|null} [opts.compare]
 * @param {Array<{title:string, content:string}>} [opts.sections]
 * @param {Array<{key:string, title:string, dataUrl:string}>} [opts.images]
 */
export async function exportReportPdfDocument(opts, targetWindow = null) {
  const images = await prepareImages(opts.images || [])
  const html = buildPrintHtml({ ...opts, images })

  let w = targetWindow
  if (!w || w.closed) {
    // 注意：不能带 noopener，否则 window.open 返回 null
    w = window.open('', '_blank', 'width=960,height=820')
  }
  if (!w) {
    throw new Error('popup_blocked')
  }

  w.document.open()
  w.document.write(html)
  w.document.close()
  try {
    w.focus()
  } catch (_) {
    /* ignore */
  }
}
