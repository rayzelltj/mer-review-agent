import React from 'react';
import './App.css';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { HomePage, PlanPage, QboCallbackPage, QboConnectPage } from './pages';
import { useWebSocket } from './hooks/useWebSocket';

function App() {
    useWebSocket();
    
  return (
    <Router>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/qbo/connect" element={<QboConnectPage />} />
        <Route path="/qbo/callback" element={<QboCallbackPage />} />
        <Route path="/plan/:planId" element={<PlanPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
