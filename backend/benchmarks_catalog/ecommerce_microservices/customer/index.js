const express = require('express');
const app = express();
app.use(express.json());

const customers = new Map();

app.post('/api/customers/register', (req, res) => {
  const { email, name } = req.body;
  if (!email || !name) {
    return res.status(400).json({ error: 'Email and name are required' });
  }
  const id = `cust_${Date.now()}`;
  const customer = { id, email, name, orders: [] };
  customers.set(id, customer);
  res.status(201).json(customer);
});

app.get('/api/customers/:id', (req, res) => {
  const customer = customers.get(req.params.id);
  if (!customer) {
    return res.status(404).json({ error: 'Customer not found' });
  }
  res.json(customer);
});

module.exports = app;
