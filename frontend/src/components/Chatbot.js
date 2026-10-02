import ChatPanel from './chat/ChatPanel';
import { useConversation } from '../hooks/useConversation';

function Chatbot() {
  const { messages, userInput, setUserInput, isTyping, sendMessage, error } = useConversation();

  return (
    <ChatPanel
      messages={messages}
      userInput={userInput}
      setUserInput={setUserInput}
      isTyping={isTyping}
      sendMessage={sendMessage}
      error={error}
    />
  );
}

export default Chatbot;
