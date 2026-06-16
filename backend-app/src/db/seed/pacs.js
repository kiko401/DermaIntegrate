require('dotenv').config();
const pacsPool = require('../pools/pacs');

async function seedPacs() {
  const patients = [
    ['PACS-RIS-ZW-007', '张伟', '110101198801015678', null],
    ['PACS-RIS-WQ-019', '王强', '310101199203207890', '13700137003'],
  ];
  for (const [sid, n, card, phone] of patients) {
    await pacsPool.execute(
      'INSERT IGNORE INTO pacs_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
      [sid, n, card, phone]
    );
  }

  const records = [
    ['PACS-RIS-ZW-007', 'PACS-RIS-ZW-007', '1.2.840.99999.007', 'DERM', '左足底', '左足底色素性皮损，皮镜检查',
     '/pacs/images/ZW-007-origin.jpg', '/pacs/images/ZW-007-thumb.jpg', '2021-03-16 14:00:00'],
    ['PACS-RIS-WQ-019', 'PACS-RIS-WQ-019', '1.2.840.99999.019', 'DERM', '背部',   '背部多发斑块皮损，皮镜检查',
     '/pacs/images/WQ-019-origin.jpg', '/pacs/images/WQ-019-thumb.jpg', '2022-07-21 11:30:00'],
  ];
  for (const [sid, rid, stuid, mod, bp, desc, imgp, tmbp, rat] of records) {
    const [[p]] = await pacsPool.execute(
      'SELECT id FROM pacs_patients WHERE source_id = ? LIMIT 1', [sid]
    );
    if (!p) continue;
    await pacsPool.execute(
      `INSERT IGNORE INTO pacs_records
         (pacs_patient_id, record_id, study_id, modality, body_part, description, image_path, thumbnail_path, recorded_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [p.id, rid, stuid, mod, bp, desc, imgp, tmbp, rat]
    );
  }

  console.log('[pacs] seed done — 2 patients, 2 records');
}

module.exports = seedPacs;
