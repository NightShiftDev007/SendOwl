import service, { requestWithRetry } from './index'

export function listDecisions() {
  return service.get('/api/decision/list')
}

export function deleteDecision(decisionId) {
  return service.delete(`/api/decision/${decisionId}`)
}

export function createDecision(body) {
  return requestWithRetry(() => service.post('/api/decision/create', body))
}

export function getDecision(decisionId) {
  return service.get(`/api/decision/${decisionId}`)
}

export function ensureDecisionSims(decisionId) {
  return requestWithRetry(() =>
    service.post(`/api/decision/${decisionId}/ensure-sims`),
  )
}

export function replaceDecisionScenarios(decisionId, body = {}) {
  return requestWithRetry(async () => {
    const res = await service.post(`/api/decision/${decisionId}/scenarios`, body)
    try {
      const { clearSimIdCache } = await import('./simulation')
      clearSimIdCache(decisionId)
    } catch (_) {
      /* ignore */
    }
    return res
  })
}

export function prepareDecision(decisionId, body = {}) {
  return requestWithRetry(() =>
    service.post(`/api/decision/${decisionId}/prepare`, body),
  )
}

export function getDecisionWorld(decisionId) {
  return service.get(`/api/decision/${decisionId}/world`)
}

export function startDecision(decisionId, body = {}) {
  return requestWithRetry(() =>
    service.post(`/api/decision/${decisionId}/start`, body),
  )
}

export function getDecisionStatus(decisionId) {
  return service.get(`/api/decision/${decisionId}/status`)
}

export function getDecisionCompare(decisionId, params = {}) {
  return service.get(`/api/decision/${decisionId}/compare`, { params })
}

export function getRun(runId) {
  return service.get(`/api/run/${runId}`)
}

export function getRunActions(runId, params = {}) {
  return service.get(`/api/run/${runId}/actions`, { params })
}

export function getRunAgents(runId) {
  return service.get(`/api/run/${runId}/agents`)
}

export function interviewRun(runId, body) {
  return service.post(`/api/run/${runId}/interview`, body)
}

export function health() {
  return service.get('/health')
}
