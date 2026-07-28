const router = require('express').Router({ mergeParams: true });
const service = require('../services/visitService');
const patientService = require('../services/patientService');

router.use(require('express').json());

router.get('/', async (req, res) => {
  try {
    res.json(await service.listByPatient(req.params.patientId));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.post('/', async (req, res) => {
  try {
    const patient = await patientService.getById(req.params.patientId);
    if (!patient) return res.status(404).json({ error: 'patient not found' });
    res.status(201).json(await service.create(req.params.patientId, req.body));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
