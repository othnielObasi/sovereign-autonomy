'use client';

import React from 'react';

interface Alert {
  id: string;
  severity: 'critical' | 'warning' | 'info';
  message: string;
  timestamp: string;
  policyId?: string;
}

interface AlertsPanelProps {
  alerts: Alert[];
  onDismiss?: (id: string) => void;
}

export default function AlertsPanel({ alerts, onDismiss }: AlertsPanelProps) {
  const getSeverityStyles = (severity: string) => {
    switch (severity) {
      case 'critical':
        return {
          bg: 'bg-red-500/10',
          border: 'border-red-500',
          icon: '🚨',
          text: 'text-red-400',
        };
      case 'warning':
        return {
          bg: 'bg-yellow-500/10',
          border: 'border-yellow-500',
          icon: '⚠️',
          text: 'text-yellow-400',
        };
      case 'info':
      default:
        return {
          bg: 'bg-blue-500/10',
          border: 'border-blue-500',
          icon: 'ℹ️',
          text: 'text-blue-400',
        };
    }
  };

  const formatTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString();
    } catch {
      return timestamp;
    }
  };

  if (alerts.length === 0) {
    return (
      <div className="text-center text-mc-dim py-4">
        <span className="text-2xl">✓</span>
        <p className="text-sm mt-1">No active alerts</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {alerts.map((alert) => {
        const styles = getSeverityStyles(alert.severity);
        return (
          <div
            key={alert.id}
            className={`p-3 rounded-lg border-l-4 ${styles.bg} ${styles.border} relative`}
          >
            <div className="flex items-start gap-2">
              <span className="text-lg">{styles.icon}</span>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className={`text-xs font-semibold uppercase ${styles.text}`}>
                    {alert.severity}
                  </span>
                  <span className="text-xs text-mc-dim">
                    {formatTime(alert.timestamp)}
                  </span>
                </div>
                <p className="text-sm text-mc-ink mt-1">{alert.message}</p>
                {alert.policyId && (
                  <p className="text-xs text-mc-dim mt-1">
                    Policy: {alert.policyId}
                  </p>
                )}
              </div>
              {onDismiss && (
                <button
                  onClick={() => onDismiss(alert.id)}
                  className="text-mc-dim hover:text-mc-ink/85 text-lg"
                >
                  ×
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
