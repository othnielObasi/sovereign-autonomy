'use client';

import React from 'react';

interface TimelineEvent {
  id: string;
  timestamp: string;
  type: 'APPROVED' | 'DENIED' | 'SLOW' | 'STOP' | 'REPLAN';
  message: string;
  riskScore?: number;
  policyId?: string;
}

interface TimelineProps {
  events: TimelineEvent[];
  maxEvents?: number;
}

export default function Timeline({ events, maxEvents = 10 }: TimelineProps) {
  const displayEvents = events.slice(0, maxEvents);

  const getEventColor = (type: string) => {
    switch (type) {
      case 'APPROVED':
        return 'border-green-500 bg-green-500/10';
      case 'DENIED':
      case 'STOP':
        return 'border-red-500 bg-red-500/10';
      case 'SLOW':
        return 'border-yellow-500 bg-yellow-500/10';
      case 'REPLAN':
        return 'border-blue-500 bg-blue-500/10';
      default:
        return 'border-mc-line2 bg-slate-500/10';
    }
  };

  const getBadgeColor = (type: string) => {
    switch (type) {
      case 'APPROVED':
        return 'bg-green-500';
      case 'DENIED':
      case 'STOP':
        return 'bg-red-500';
      case 'SLOW':
        return 'bg-yellow-500 text-black';
      case 'REPLAN':
        return 'bg-blue-500';
      default:
        return 'bg-slate-500';
    }
  };

  const formatTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString();
    } catch {
      return timestamp;
    }
  };

  if (events.length === 0) {
    return (
      <div className="text-center text-mc-dim py-8">
        No events yet
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {displayEvents.map((event, index) => (
        <div
          key={event.id}
          className={`p-3 rounded-lg border-l-4 ${getEventColor(event.type)}`}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-mc-mute">
              {formatTime(event.timestamp)}
            </span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded ${getBadgeColor(event.type)}`}>
              {event.type}
            </span>
          </div>
          <p className="text-sm text-mc-ink">{event.message}</p>
          {(event.riskScore !== undefined || event.policyId) && (
            <div className="flex gap-3 mt-1 text-xs text-mc-dim">
              {event.riskScore !== undefined && (
                <span>Risk: {event.riskScore.toFixed(2)}</span>
              )}
              {event.policyId && (
                <span>Policy: {event.policyId}</span>
              )}
            </div>
          )}
        </div>
      ))}
      
      {events.length > maxEvents && (
        <div className="text-center text-xs text-mc-dim pt-2">
          +{events.length - maxEvents} more events
        </div>
      )}
    </div>
  );
}
