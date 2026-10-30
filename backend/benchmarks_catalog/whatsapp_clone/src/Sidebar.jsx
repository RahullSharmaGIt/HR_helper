import React, { useState, useEffect } from 'react';
import { Avatar, IconButton } from '@mui/material';

function Sidebar({ onSelectRoom, db }) {
  const [rooms, setRooms] = useState([]);

  useEffect(() => {
    if (!db) return;
    const unsubscribe = db.collection('rooms').onSnapshot((snapshot) => {
      setRooms(snapshot.docs.map((doc) => ({ id: doc.id, data: doc.data() })));
    });
    return () => unsubscribe();
  }, [db]);

  const createChat = () => {
    const roomName = prompt('Please enter name for chat room');
    if (roomName && db) {
      db.collection('rooms').add({ name: roomName, createdAt: new Date().toISOString() });
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar__header">
        <Avatar />
        <div className="sidebar__headerRight">
          <button onClick={createChat} className="sidebar__addBtn">Add Chat</button>
        </div>
      </div>
      <div className="sidebar__chats">
        {rooms.map((room) => (
          <div key={room.id} onClick={() => onSelectRoom(room.id)} className="sidebarChat">
            <Avatar src={`https://avatars.dicebear.com/api/human/${room.id}.svg`} />
            <div className="sidebarChat__info">
              <h2>{room.data.name}</h2>
              <p>Recent conversation message...</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default Sidebar;
