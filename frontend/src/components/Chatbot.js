import React from 'react';
import './Chatbot.css';
import { useConversation } from '../hooks/useConversation';

function Chatbot() {
  const { messages, userInput, setUserInput, isTyping, sendMessage } = useConversation();

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
