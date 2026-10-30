const express = require('express');
const app = express();
app.use(express.json());

const inventory = new Map();

app.post('/api/products', (req, res) => {
  const { name, price, stock, category } = req.body;
  if (!name || price == null) {
    return res.status(400).json({ error: 'Product name and price are required' });
  }
  const id = `prod_${Date.now()}`;
  const product = { id, name, price, stock: stock || 0, category: category || 'general' };
  inventory.set(id, product);
  res.status(201).json(product);
});

app.get('/api/products/:id', (req, res) => {
  const product = inventory.get(req.params.id);
  if (!product) {
    return res.status(404).json({ error: 'Product not found' });
  }
  res.json(product);
});

module.exports = app;
