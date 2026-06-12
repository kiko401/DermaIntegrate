const router = require('express').Router();
const service = require('../services/patientService');

router.use(require('express').json());

router.get('/', async (req, res) => {
  try {
    res.json(await service.list());
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/:id', async (req, res) => {
  try {
    const patient = await service.getById(req.params.id);
    if (!patient) return res.status(404).json({ error: 'not found' });
    res.json(patient);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.post('/', async (req, res) => {
  try {
    const { name } = req.body;
    if (!name) return res.status(400).json({ error: 'name is required' });
    res.status(201).json(await service.create(req.body));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.put('/:id', async (req, res) => {
  try {
    const patient = await service.update(req.params.id, req.body);
    if (!patient) return res.status(404).json({ error: 'not found' });
    res.json(patient);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.delete('/:id', async (req, res) => {
  try {
    const ok = await service.remove(req.params.id);
    if (!ok) return res.status(404).json({ error: 'not found' });
    res.status(204).end();
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
