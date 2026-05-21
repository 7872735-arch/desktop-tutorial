const express = require('express');
const Database = require('better-sqlite3');

const db = new Database(':memory:');

db.exec(`
  CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  )
`);

const app = express();
app.use(express.json());

app.get('/jobs', (req, res) => {
  const jobs = db.prepare('SELECT * FROM jobs ORDER BY id DESC').all();
  res.json(jobs);
});

app.post('/jobs', (req, res) => {
  const { title, company, status = 'applied' } = req.body;
  if (!title || !company) {
    return res.status(400).json({ error: 'title and company are required' });
  }
  const result = db.prepare(
    'INSERT INTO jobs (title, company, status) VALUES (?, ?, ?)'
  ).run(title, company, status);
  const job = db.prepare('SELECT * FROM jobs WHERE id = ?').get(result.lastInsertRowid);
  res.status(201).json(job);
});

app.patch('/jobs/:id', (req, res) => {
  const { id } = req.params;
  const { title, company, status } = req.body;
  const job = db.prepare('SELECT * FROM jobs WHERE id = ?').get(id);
  if (!job) {
    return res.status(404).json({ error: 'Job not found' });
  }
  const updated = db.prepare(
    'UPDATE jobs SET title = ?, company = ?, status = ? WHERE id = ?'
  ).run(
    title ?? job.title,
    company ?? job.company,
    status ?? job.status,
    id
  );
  const updatedJob = db.prepare('SELECT * FROM jobs WHERE id = ?').get(id);
  res.json(updatedJob);
});

app.get('/jobs/summary', (req, res) => {
  const total = db.prepare('SELECT COUNT(*) as count FROM jobs').get().count;
  const byStatus = db.prepare(
    'SELECT status, COUNT(*) as count FROM jobs GROUP BY status'
  ).all();
  res.json({ total, byStatus });
});

module.exports = { app };
