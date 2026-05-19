"use client";

import {
    createContext,
    useContext,
    useState,
    useCallback,
    type ReactNode,
} from "react";
import { api } from "@/lib/api";

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    timestamp: Date;
    thinking?: string;
}

interface ChatContextValue {
    messages: Message[];
    isLoading: boolean;
    sendMessage: (text: string, kb: string) => void;
    clearMessages: () => void;
}

const ChatContext = createContext<ChatContextValue>({
    messages: [],
    isLoading: false,
    sendMessage: () => { },
    clearMessages: () => { },
});

export function ChatProvider({ children }: { children: ReactNode }) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);

    const sendMessage = useCallback((text: string, kb: string) => {
        if (!text.trim() || isLoading) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: "user",
            content: text,
            timestamp: new Date(),
        };

        setMessages((prev) => [...prev, userMessage]);
        setIsLoading(true);

        // Fire-and-forget — runs even if the chat page is not mounted.
        api
            .chat(text, kb)
            .then((response) => {
                const assistantMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: response.answer || "I couldn't generate a response.",
                    timestamp: new Date(),
                    thinking: response.thinking || undefined,
                };
                setMessages((prev) => [...prev, assistantMessage]);
            })
            .catch(() => {
                const errorMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: "Sorry, I encountered an error. Please try again.",
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, errorMessage]);
            })
            .finally(() => {
                setIsLoading(false);
            });
    }, [isLoading]);

    const clearMessages = useCallback(() => {
        setMessages([]);
    }, []);

    return (
        <ChatContext.Provider value={{ messages, isLoading, sendMessage, clearMessages }}>
            {children}
        </ChatContext.Provider>
    );
}

export function useChat() {
    return useContext(ChatContext);
}
