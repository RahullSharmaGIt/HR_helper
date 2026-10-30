import React, { useState, useEffect } from 'react';
import { Avatar } from '@mui/material';

function Chat({ roomId, db }) {
  const [input, setInput] = useState('');
  const [roomName, setRoomName] = useState('');
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    if (roomId && db) {
      db.collection('rooms').doc(roomId).onSnapshot((snapshot) => {
        setRoomName(snapshot.data()?.name || '');
      });
      db.collection('rooms').doc(roomId).collection('messages').orderBy('timestamp', 'asc').onSnapshot((snapshot) => {
        setMessages(snapshot.docs.map((doc) => doc.data()));
      });
    }
  }, [roomId, db]);

  const sendMessage = (e) => {
    e.preventDefault();
    if (!input.trim() || !roomId || !db) return;
    db.collection('rooms').doc(roomId).collection('messages').add({
      message: input,
      name: 'User',
      timestamp: new Date().toISOString(),
    });
    setInput('');
  };

  return (
    <div className="chat">
      <div className="chat__header">
        <Avatar src={`https://avatars.dicebear.com/api/human/${roomId}.svg`} />
        <div className="chat__headerInfo">
          <h3>{roomName}</h3>
          <p>Last seen at {messages[messages.length - 1]?.timestamp || 'recently'}</p>
        </div>
      </div>
      <div className="chat__body">
        {messages.map((msg, idx) => (
          <p key={idx} className={`chat__message ${msg.name === 'User' && 'chat__receiver'}`}>
            <span className="chat__name">{msg.name}</span>
            {msg.message}
            <span className="chat__timestamp">{new Date(msg.timestamp).toLocaleTimeString()}</span>
          </p>
        ))}
      </div>
      <div className="chat__footer">
        <form onSubmit={sendMessage}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message"
            type="text"
          />
          <button type="submit">Send</button>
        </form>
      </div>
    </div>
  );
}

export default Chat;
