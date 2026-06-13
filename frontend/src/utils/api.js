export async function apiFetch(url, options = {}) {
  const token = localStorage.getItem('auth_token')
  const res = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
  if (res.status === 401) {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('doctor_info')
    window.location.href = '/login'
  }
  return res
}
