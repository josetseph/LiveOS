import React from "react";

interface ServiceBadgeProps {
    label: string;
    color: string;
}

export function ServiceBadge({ label, color }: ServiceBadgeProps) {
    return (
        <span className={`font-medium ${color}`}>{label}</span>
    );
}
