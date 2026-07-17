import service, { requestWithRetry } from './index'

/** 创建本体（上传文档） */
export function createOntology(formData) {
  return requestWithRetry(() =>
    service({
      url: '/api/ontology/create',
      method: 'post',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  )
}

/** 首页加载 GTV 现实种子演示包 */
export function fetchGtvDemoPack() {
  return service.get('/api/ontology/gtv-demo-pack')
}

/** CRM 种子底座就绪状态（房源/经纪人/签约规模） */
export function fetchGtvSeedStatus() {
  return service.get('/api/ontology/gtv-seed-status')
}

/** 兼容旧名：首页/工作台仍可能调用 generateOntology */
export function generateOntology(formData) {
  return createOntology(formData)
}

export function listOntologies() {
  return service.get('/api/ontology/list')
}

export function deleteOntology(ontologyId) {
  return service.delete(`/api/ontology/${ontologyId}`)
}

export function getOntology(ontologyId) {
  return service.get(`/api/ontology/${ontologyId}`)
}

/** 兼容旧名 getProject */
export function getProject(ontologyId) {
  return getOntology(ontologyId)
}

export function buildOntology(ontologyId, data = {}) {
  return requestWithRetry(() =>
    service.post(`/api/ontology/${ontologyId}/build`, {
      use_existing_schema: true,
      async: true,
      ...data,
    }),
  )
}

/** 兼容旧名 buildGraph({ project_id }) */
export function buildGraph(data) {
  const ontologyId = data.project_id || data.ontology_id
  return buildOntology(ontologyId, data)
}

export function getBuildStatus(ontologyId, taskId) {
  return service.get(`/api/ontology/${ontologyId}/build/status`, {
    params: { task_id: taskId },
  })
}

/** 兼容旧名 getTaskStatus */
export function getTaskStatus(taskId, ontologyId) {
  // ADC 需要 ontology_id；若仅有 taskId，调用方应传 ontologyId
  if (!ontologyId) {
    return Promise.resolve({
      success: true,
      data: { task_id: taskId, status: 'unknown' },
    })
  }
  return getBuildStatus(ontologyId, taskId)
}

export function snapshotOntology(ontologyId) {
  return service.post(`/api/ontology/${ontologyId}/snapshot`)
}

export function listVersions(ontologyId) {
  return service.get(`/api/ontology/${ontologyId}/versions`)
}

/**
 * 读图：默认本地快照；建图中读 Zep live。
 * 强制对齐 Zep：先 snapshotOntology 再调本方法。
 */
export function getOntologyGraph(ontologyId) {
  return service.get(`/api/ontology/${ontologyId}/graph`)
}

/**
 * 兼容旧名 getGraphData —— ADC 用 ontologyId。
 * 统一走 /graph（默认快照）。
 */
export function getGraphData(ontologyId) {
  return getOntologyGraph(ontologyId)
}

export function appendDocuments(ontologyId, formData) {
  return service({
    url: `/api/ontology/${ontologyId}/documents`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
