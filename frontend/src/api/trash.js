import service from './index'

export function listTrash() {
  return service.get('/api/trash')
}

export function restoreTrashItem(kind, id) {
  return service.post(`/api/trash/${kind}/${id}/restore`)
}

export function purgeTrashItem(kind, id) {
  return service.delete(`/api/trash/${kind}/${id}`)
}
