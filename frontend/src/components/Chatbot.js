import ChatPanel from './chat/ChatPanel';
import { useConversation } from '../hooks/useConversation';

function Chatbot() {
  const { messages, userInput, setUserInput, isTyping, sendMessage } = useConversation();

  return (
    <ChatPanel
      messages={messages}
      userInput={userInput}
      setUserInput={setUserInput}
      isTyping={isTyping}
      sendMessage={sendMessage}
    />
  );
}

export default Chatbot;
