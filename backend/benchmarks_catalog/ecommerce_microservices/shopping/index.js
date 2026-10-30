const express = require('express');
const app = express();
app.use(express.json());

const orders = new Map();

app.post('/api/shopping/order', (req, res) => {
  const { customerId, items } = req.body;
  if (!customerId || !Array.isArray(items) || items.length === 0) {
    return res.status(400).json({ error: 'Valid customerId and items list required' });
  }
  const orderId = `ord_${Date.now()}`;
  const totalAmount = items.reduce((sum, item) => sum + (item.price * item.quantity), 0);
  const order = {
    orderId,
    customerId,
    items,
    totalAmount,
    status: 'PLACED',
    createdAt: new Date().toISOString(),
  };
  orders.set(orderId, order);
  res.status(201).json(order);
});

module.exports = app;
