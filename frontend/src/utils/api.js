export async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    credentials: 'include',
    headers: { ...options.headers },
  })
  if (res.status === 401) {
    localStorage.removeItem('doctor_info')
    window.location.href = '/login'
  }
  return res
}
