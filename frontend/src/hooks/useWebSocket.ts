import { useEffect, useRef, useState } from 'react';
import type { ProgressUpdate } from '../types/analysis';

export const useWebSocket = (jobId: string | null) => {
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const wsUrl = `ws://localhost:8000/api/analysis/${jobId}/progress`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      const data: ProgressUpdate = JSON.parse(event.data);
      setProgress(data.progress);
      setMessage(data.message);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
      setIsConnected(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [jobId]);

  return { progress, message, isConnected };
};
