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
        let interval: number | null = null;

        const fail = () => {
            if (interval !== null) window.clearInterval(interval);
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: "assistant",
                content: "Sorry, I encountered an error. Please try again.",
                timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMessage]);
            setIsLoading(false);
            setLoadingStage(null);
            setLoadingModel(null);
        };

        const complete = (answer?: string, thinking?: string | null) => {
            if (interval !== null) window.clearInterval(interval);
            const assistantMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: "assistant",
                content: answer || "I couldn't generate a response.",
                timestamp: new Date(),
                thinking: thinking || undefined,
            };
            setMessages((prev) => [...prev, assistantMessage]);
            setIsLoading(false);
            setLoadingStage(null);
            setLoadingModel(null);
        };

        const poll = () => {
            api.getChatStatus(requestId)
                .then((status) => {
                    setLoadingStage(status.stage);
                    setLoadingModel(status.model ?? null);
                    if (!status.done) return;
                    if (status.error) {
                        fail();
                        return;
                    }
                    complete(status.result?.answer, status.result?.thinking);
                })
                .catch(() => { });
        };

        api
            .startChat(text, kb, requestId)
            .then(() => {
                interval = window.setInterval(poll, 1000);
                poll();
            })
            .catch(() => {
                const errorMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: "Sorry, I encountered an error. Please try again.",
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, errorMessage]);
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
