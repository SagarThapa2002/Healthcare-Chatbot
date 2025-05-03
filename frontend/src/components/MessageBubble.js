import React from 'react';

const MessageBubble = ({ sender, text }) => {
  const isUser = sender === "You";
  return (
    <div className={`d-flex ${isUser ? "justify-content-end" : "justify-content-start"} mb-2`}>
      <div className={`p-2 rounded ${isUser ? "bg-primary text-white" : "bg-light border"}`}>
        <strong>{sender}:</strong> {text}
      </div>
    </div>
  );
};

export default MessageBubble;
