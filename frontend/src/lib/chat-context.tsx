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
    loadingStage: string | null;
    loadingModel: string | null;
    sendMessage: (text: string, kb: string) => void;
    clearMessages: () => void;
}

const ChatContext = createContext<ChatContextValue>({
    messages: [],
    isLoading: false,
    loadingStage: null,
    loadingModel: null,
    sendMessage: () => { },
    clearMessages: () => { },
});

export function ChatProvider({ children }: { children: ReactNode }) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [loadingStage, setLoadingStage] = useState<string | null>(null);
    const [loadingModel, setLoadingModel] = useState<string | null>(null);

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
        setLoadingStage("Starting chat request");
        setLoadingModel(null);

        const requestId =
            typeof crypto !== "undefined" && "randomUUID" in crypto
                ? crypto.randomUUID()
                : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const interval = window.setInterval(() => {
            api.getChatStatus(requestId)
                .then((status) => {
                    setLoadingStage(status.stage);
                    setLoadingModel(status.model ?? null);
                })
                .catch(() => { });
        }, 1000);

        // Fire-and-forget — runs even if the chat page is not mounted.
        api
            .chat(text, kb, requestId)
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
                window.clearInterval(interval);
                setIsLoading(false);
                setLoadingStage(null);
                setLoadingModel(null);
            });
    }, [isLoading]);

    const clearMessages = useCallback(() => {
        setMessages([]);
    }, []);

    return (
        <ChatContext.Provider
            value={{
                messages,
                isLoading,
                loadingStage,
                loadingModel,
                sendMessage,
                clearMessages,
            }}
        >
            {children}
        </ChatContext.Provider>
    );
}

export function useChat() {
    return useContext(ChatContext);
}
