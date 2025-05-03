import React, { useState } from 'react';
import MessageBubble from './MessageBubble';

const ChatWindow = () => {
  const [messages, setMessages] = useState([
    { sender: "Bot", text: "Hi! I'm your virtual healthcare assistant. How can I help you today?" }
  ]);
  const [input, setInput] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage = { sender: "You", text: input };
    setMessages([...messages, userMessage]);

    try {
      const res = await fetch("http://127.0.0.1:5000/webhook/webhook", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          queryResult: {
            intent: { displayName: detectIntent(input) },
            parameters: parseParams(input)
          }
        })
      });

      const data = await res.json();
      setMessages(prev => [...prev, { sender: "Bot", text: data.fulfillmentText }]);
    } catch (err) {
      setMessages(prev => [...prev, { sender: "Bot", text: "Error reaching server." }]);
    }

    setInput("");
  };

  return (
    <>
      <div className="chat-box border rounded p-3 bg-white mb-3" style={{ height: "400px", overflowY: "auto" }}>
        {messages.map((msg, idx) => (
          <MessageBubble key={idx} sender={msg.sender} text={msg.text} />
        ))}
      </div>
      <form className="d-flex" onSubmit={handleSubmit}>
        <input
          className="form-control me-2"
          placeholder="Type your message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className="btn btn-primary">Send</button>
      </form>
    </>
  );
};

function detectIntent(msg) {
  msg = msg.toLowerCase();
  if (msg.includes("book")) return "Book Appointment";
  if (msg.includes("cancel")) return "Cancel Appointment";
  if (msg.includes("update")) return "Update Appointment";
  if (msg.includes("view")) return "View Appointments";
  if (msg.includes("symptom")) return "Symptom Check";
  return "General FAQ";
}

function parseParams(msg) {
  const params = {};
  const date = msg.match(/\d{4}-\d{2}-\d{2}/);
  const time = msg.match(/\d{2}:\d{2}/);
  const name = msg.match(/(?:for|name is)\s([A-Z][a-z]+\s[A-Z][a-z]+)/i);
  if (date) params.date = date[0];
  if (time) params.time = time[0];
  if (name) params.name = name[1];
  return params;
}

export default ChatWindow;
