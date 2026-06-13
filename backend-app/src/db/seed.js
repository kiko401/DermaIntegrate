require('dotenv').config()
const bcrypt = require('bcryptjs')
const db = require('./index')

async function seed() {
  const name = process.env.DEMO_DOCTOR_NAME || '演示医生'
  const username = process.env.DEMO_DOCTOR_USERNAME || 'doctor'
  const password = process.env.DEMO_DOCTOR_PASSWORD || 'demo123'
  const hash = await bcrypt.hash(password, 10)

  await db.execute(
    'INSERT IGNORE INTO doctors (name, username, password_hash) VALUES (?, ?, ?)',
    [name, username, hash]
  )
  console.log(`Seed done. username: ${username}  password: ${password}`)
  process.exit(0)
}

seed().catch(e => { console.error(e); process.exit(1) })
