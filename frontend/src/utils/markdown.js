/**
 * 轻量 Markdown → HTML（与 Step4/Step5 行为对齐，并支持 GFM 表格）
 */
export function renderMarkdown(content, { stripLeadingH2 = false } = {}) {
  if (!content) return ''

  let processed = String(content)
  if (stripLeadingH2) {
    processed = processed.replace(/^##\s+.+\n+/, '')
  }

  // 先抽出表格，避免被换行/列表规则拆坏
  const tables = []
  processed = processed.replace(/(^|\n)((?:\|.+\|\n)+)/g, (match, lead, block) => {
    const lines = block.trim().split('\n').filter((l) => l.trim().startsWith('|'))
    if (lines.length < 2) return match
    const sep = lines[1].replace(/\s/g, '')
    if (!/^\|?(:?-+:?\|)+(:?-+:?)?$/.test(sep) && !/^\|[-:|]+$/.test(sep)) {
      return match
    }
    const idx = tables.length
    tables.push(lines)
    return `${lead}%%MDTABLE${idx}%%\n`
  })

  let html = processed.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    '<pre class="code-block"><code>$2</code></pre>',
  )
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  html = html.replace(/^(\s*)- (.+)$/gm, (match, indent, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${text}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, _num, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${text}</li>`
  })

  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')
  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^---$/gm, '<hr class="md-hr">')

  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = `<p class="md-p">${html}</p>`

  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr|%%MDTABLE)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>|%%MDTABLE\d+%%)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote|%%MDTABLE)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|%%MDTABLE\d+%%)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr|%%MDTABLE)/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/(<\/ol>|<\/ul>|<\/blockquote>)<br>(<p|<div)/g, '$1$2')

  // 还原表格
  html = html.replace(/%%MDTABLE(\d+)%%/g, (_, i) => tableToHtml(tables[Number(i)] || []))

  // 清理表格周围的段落/br
  html = html.replace(/<p class="md-p">(<div class="md-table-wrap">[\s\S]*?<\/div>)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<div class="md-table-wrap")/g, '$1')
  html = html.replace(/(<\/div>)\s*<br>/g, '$1')

  return html
}

function parseRow(row) {
  return row
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())
}

function inlineFormat(text) {
  return String(text || '')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
}

function tableToHtml(lines) {
  if (!lines.length) return ''
  const headers = parseRow(lines[0])
  const body = lines.slice(2).map(parseRow)
  const th = headers.map((h) => `<th>${inlineFormat(h)}</th>`).join('')
  const trs = body
    .map((cells) => {
      const tds = headers
        .map((_, i) => `<td>${inlineFormat(cells[i] ?? '')}</td>`)
        .join('')
      return `<tr>${tds}</tr>`
    })
    .join('')
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`
}
