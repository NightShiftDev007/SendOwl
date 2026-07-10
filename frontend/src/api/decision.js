import service, { requestWithRetry } from './index'

export function listDecisions() {
  return service.get('/api/decision/list')
}

export function createDecision(body) {
  return requestWithRetry(() => service.post('/api/decision/create', body))
}

export function getDecision(decisionId) {
  return service.get(`/api/decision/${decisionId}`)
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

export function interviewRun(runId, body) {
  return service.post(`/api/run/${runId}/interview`, body)
}

export function health() {
  return service.get('/health')
}
