import React from 'react';
import Chatbot from './components/Chatbot'; // Corrected component name
import './App.css';

function App() {
  return (
    <div className="App bg-light min-vh-100">
      <div className="container py-5">
        <h2 className="text-center mb-4">💬 Healthcare Chatbot</h2>
        <Chatbot /> {/* Use the correct component here */}
      </div>
    </div>
  );
}

export default App;
