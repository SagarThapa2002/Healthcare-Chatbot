import React, { useState } from 'react';
import './Chatbot.css';

function Chatbot() {
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!userInput.trim()) return;

    const newMessages = [...messages, { sender: 'user', text: userInput }];
    setMessages(newMessages);
    setUserInput('');
    setIsTyping(true);

    try {
      const response = await fetch('http://127.0.0.1:5000/webhook/webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          queryResult: {
            intent: { displayName: "General FAQ" },
            parameters: { user_message: userInput }
          }
        })
      });

      const data = await response.json();
      setMessages([...newMessages, { sender: 'bot', text: data.fulfillmentText }]);
    } catch (err) {
      console.error(err);
      setMessages([...newMessages, { sender: 'bot', text: "Sorry, an error occurred." }]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-header">Healthcare Chatbot</div>
      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.sender}`}>
            <div className="text">{msg.text}</div>
          </div>
        ))}
        {isTyping && <div className="message bot"><div className="text typing">Bot is typing...</div></div>}
      </div>
      <form className="chat-input" onSubmit={sendMessage}>
        <input
          type="text"
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          placeholder="Type your message..."
        />
        <button type="submit">Send</button>
      </form>
    </div>
  );
}

export default Chatbot;
