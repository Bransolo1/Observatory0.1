"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { chat, type ChatMessage } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import {
  MessageSquare,
  Plus,
  Send,
  Loader2,
  Trash2,
  Wrench,
  Bot,
  User,
  Users,
  ChevronDown,
  ChevronUp,
  ThumbsUp,
  ThumbsDown,
  Square,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

const SPECIALIST_COLORS: Record<string, string> = {
  behavioural_scientist: "border-purple-300 bg-purple-50 dark:border-purple-700 dark:bg-purple-950/30",
  consumer_researcher: "border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/30",
  clinical_psychologist: "border-rose-300 bg-rose-50 dark:border-rose-700 dark:bg-rose-950/30",
  qualitative_specialist: "border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30",
  data_scientist: "border-cyan-300 bg-cyan-50 dark:border-cyan-700 dark:bg-cyan-950/30",
  clinical_lead: "border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-950/30",
  ux_researcher: "border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-950/30",
  business_strategist: "border-orange-300 bg-orange-50 dark:border-orange-700 dark:bg-orange-950/30",
};

const SPECIALIST_PILL_COLORS: Record<string, string> = {
  behavioural_scientist: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  consumer_researcher: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  clinical_psychologist: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  qualitative_specialist: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  data_scientist: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300",
  clinical_lead: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  ux_researcher: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  business_strategist: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
};

interface ToolActivity {
  name: string;
  status: "running" | "done";
  preview?: string;
}

interface SpecialistActivity {
  specialist: string;
  displayName: string;
  question: string;
  status: "consulting" | "done";
  tools: ToolActivity[];
  preview?: string;
}

export default function ChatPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";

  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);
  const [specialists, setSpecialists] = useState<SpecialistActivity[]>([]);
  const [expandedSpecialists, setExpandedSpecialists] = useState<Set<string>>(new Set());
  const [feedbackGiven, setFeedbackGiven] = useState<Record<string, string>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const { data: conversations, refetch: refetchConversations } = useQuery({
    queryKey: ["chat-conversations", orgId],
    queryFn: () => chat.conversations(orgId),
    enabled: !!orgId,
  });

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingText, specialists, scrollToBottom]);

  const loadConversation = async (convId: string) => {
    setActiveConvId(convId);
    try {
      const data = await chat.messages(orgId, convId);
      setMessages(data.messages);
    } catch {
      setMessages([]);
    }
  };

  const createConversation = async () => {
    const conv = await chat.create(orgId);
    setActiveConvId(conv.id);
    setMessages([]);
    refetchConversations();
  };

  const deleteConversation = async (convId: string) => {
    await chat.delete(orgId, convId);
    if (activeConvId === convId) {
      setActiveConvId(null);
      setMessages([]);
    }
    refetchConversations();
  };

  const toggleSpecialist = (specialist: string) => {
    setExpandedSpecialists((prev) => {
      const next = new Set(prev);
      if (next.has(specialist)) next.delete(specialist);
      else next.add(specialist);
      return next;
    });
  };

  const stopStreaming = () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  };

  const giveFeedback = async (msgId: string, rating: "up" | "down") => {
    if (!activeConvId) return;
    setFeedbackGiven((prev) => ({ ...prev, [msgId]: rating }));
    try {
      const token = localStorage.getItem("observatory_token");
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/orgs/${orgId}/chat/conversations/${activeConvId}/messages/${msgId}/feedback`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
    } catch { /* silent */ }
  };

  const sendMessage = async () => {
    if (!input.trim() || isStreaming) return;

    let convId = activeConvId;
    if (!convId) {
      const conv = await chat.create(orgId);
      convId = conv.id;
      setActiveConvId(convId);
      refetchConversations();
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsStreaming(true);
    setStreamingText("");
    setToolActivity([]);
    setSpecialists([]);
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await chat.sendMessage(orgId, convId, userMessage.content);
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "text") {
              fullText += event.content;
              setStreamingText(fullText);
            } else if (event.type === "tool_start") {
              if (event.name !== "consult_specialist") {
                setToolActivity((prev) => [...prev, { name: event.name, status: "running" }]);
              }
            } else if (event.type === "tool_result") {
              setToolActivity((prev) =>
                prev.map((t) =>
                  t.name === event.name && t.status === "running"
                    ? { ...t, status: "done", preview: event.preview }
                    : t
                )
              );
            } else if (event.type === "specialist_start") {
              setSpecialists((prev) => [
                ...prev,
                {
                  specialist: event.specialist,
                  displayName: event.display_name || event.specialist,
                  question: event.question,
                  status: "consulting",
                  tools: [],
                },
              ]);
              setExpandedSpecialists((prev) => new Set([...prev, event.specialist]));
            } else if (event.type === "specialist_tool") {
              setSpecialists((prev) =>
                prev.map((s) =>
                  s.specialist === event.specialist && s.status === "consulting"
                    ? {
                        ...s,
                        tools:
                          event.status === "running"
                            ? [...s.tools, { name: event.tool, status: "running" }]
                            : s.tools.map((t) =>
                                t.name === event.tool && t.status === "running"
                                  ? { ...t, status: "done" }
                                  : t
                              ),
                      }
                    : s
                )
              );
            } else if (event.type === "specialist_done") {
              setSpecialists((prev) =>
                prev.map((s) =>
                  s.specialist === event.specialist && s.status === "consulting"
                    ? { ...s, status: "done", preview: event.preview }
                    : s
                )
              );
            } else if (event.type === "error") {
              fullText += `\n\n**Error:** ${event.message}`;
              setStreamingText(fullText);
            }
          } catch {
            // skip malformed events
          }
        }
      }

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: fullText,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setStreamingText("");
      setToolActivity([]);
      setSpecialists([]);
      refetchConversations();
    } catch (err) {
      const errorMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `**Error:** ${err instanceof Error ? err.message : "Failed to send message"}`,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  function timeAgo(dateStr: string): string {
    const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
    if (seconds < 60) return "now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] max-w-6xl">
      {/* Conversation sidebar */}
      <div className="w-64 border-r flex flex-col shrink-0">
        <div className="p-3 border-b">
          <Button size="sm" className="w-full" onClick={createConversation}>
            <Plus className="h-3 w-3 mr-1" /> New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {(conversations || []).map((conv) => (
            <div
              key={conv.id}
              className={`flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-muted/50 text-sm group ${
                activeConvId === conv.id ? "bg-muted" : ""
              }`}
              onClick={() => loadConversation(conv.id)}
            >
              <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate">{conv.title}</span>
              <span className="text-[10px] text-muted-foreground shrink-0">{timeAgo(conv.updated_at)}</span>
              <button
                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                onClick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
          {(!conversations || conversations.length === 0) && (
            <p className="text-xs text-muted-foreground text-center mt-8 px-4">
              No conversations yet. Click &quot;New Chat&quot; to start.
            </p>
          )}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Users className="h-12 w-12 text-muted-foreground mb-4" />
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-lg font-semibold">Chief Consumer Officer</h2>
                <Badge variant="secondary" className="text-[10px]">
                  <Sparkles className="h-2.5 w-2.5 mr-0.5" /> AI-Powered
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground max-w-md">
                I lead a team of 8 AI specialist analysts — behavioural scientists, researchers,
                clinicians, strategists, and more. Ask me anything and I&apos;ll consult the right
                experts to give you a synthesized, multi-lens answer.
              </p>
              <div className="flex flex-wrap gap-2 mt-4 max-w-lg justify-center">
                {[
                  "How should we improve checkout conversion?",
                  "What research should we commission next?",
                  "Do a full competitive sweep",
                  "Where are our biggest friction points?",
                  "What does the behavioural science say about our onboarding?",
                ].map((prompt) => (
                  <button
                    key={prompt}
                    className="text-xs px-3 py-1.5 rounded-full border hover:bg-muted transition-colors"
                    onClick={() => { setInput(prompt); textareaRef.current?.focus(); }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                  <Users className="h-4 w-4 text-primary" />
                </div>
              )}
              <div
                className={`max-w-[80%] ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground rounded-2xl rounded-br-md px-4 py-2"
                    : "prose prose-sm dark:prose-invert max-w-none"
                }`}
              >
                {msg.role === "user" ? (
                  <p className="text-sm">{msg.content}</p>
                ) : (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                )}
                {msg.role === "assistant" && (
                  <div className="flex items-center gap-1 mt-2">
                    <button
                      onClick={() => giveFeedback(msg.id, "up")}
                      className={`p-1 rounded hover:bg-muted transition-colors ${feedbackGiven[msg.id] === "up" ? "text-green-600" : "text-muted-foreground"}`}
                      aria-label="Helpful response"
                    >
                      <ThumbsUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => giveFeedback(msg.id, "down")}
                      className={`p-1 rounded hover:bg-muted transition-colors ${feedbackGiven[msg.id] === "down" ? "text-red-600" : "text-muted-foreground"}`}
                      aria-label="Unhelpful response"
                    >
                      <ThumbsDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
              {msg.role === "user" && (
                <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                  <User className="h-4 w-4" />
                </div>
              )}
            </div>
          ))}

          {/* Streaming state */}
          {isStreaming && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <Users className="h-4 w-4 text-primary" />
              </div>
              <div className="flex-1 space-y-3">
                {/* Direct tool activity */}
                {toolActivity.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {toolActivity.map((tool, i) => (
                      <span
                        key={i}
                        className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full ${
                          tool.status === "running"
                            ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                            : "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                        }`}
                      >
                        {tool.status === "running" ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        ) : (
                          <Wrench className="h-2.5 w-2.5" />
                        )}
                        {tool.name.replace("observatory_", "")}
                      </span>
                    ))}
                  </div>
                )}

                {/* Specialist consultation cards */}
                {specialists.map((spec) => (
                  <div
                    key={spec.specialist}
                    className={`border rounded-lg p-3 text-sm ${SPECIALIST_COLORS[spec.specialist] || "border-gray-300 bg-gray-50"}`}
                  >
                    <div
                      className="flex items-center gap-2 cursor-pointer"
                      onClick={() => toggleSpecialist(spec.specialist)}
                    >
                      {spec.status === "consulting" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
                      ) : (
                        <Bot className="h-3.5 w-3.5 shrink-0" />
                      )}
                      <span className="font-medium text-xs">{spec.displayName}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${SPECIALIST_PILL_COLORS[spec.specialist] || ""}`}>
                        {spec.status === "consulting" ? "analyzing..." : "done"}
                      </span>
                      <span className="ml-auto">
                        {expandedSpecialists.has(spec.specialist) ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </span>
                    </div>

                    {expandedSpecialists.has(spec.specialist) && (
                      <div className="mt-2 space-y-1.5">
                        <p className="text-[11px] text-muted-foreground italic">&quot;{spec.question}&quot;</p>

                        {spec.tools.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {spec.tools.map((tool, i) => (
                              <span
                                key={i}
                                className={`inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full ${
                                  tool.status === "running"
                                    ? "bg-white/50 dark:bg-black/20"
                                    : "bg-white/80 dark:bg-black/30"
                                }`}
                              >
                                {tool.status === "running" ? (
                                  <Loader2 className="h-2 w-2 animate-spin" />
                                ) : (
                                  <Wrench className="h-2 w-2" />
                                )}
                                {tool.name.replace("observatory_", "")}
                              </span>
                            ))}
                          </div>
                        )}

                        {spec.status === "done" && spec.preview && (
                          <p className="text-[11px] text-muted-foreground mt-1 line-clamp-3">
                            {spec.preview}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                ))}

                {/* Streaming text */}
                {streamingText ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingText}</ReactMarkdown>
                  </div>
                ) : specialists.length === 0 && toolActivity.length === 0 ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Thinking...
                  </div>
                ) : null}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t p-4">
          <div className="flex gap-2 max-w-3xl mx-auto">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={activeConvId ? "Ask the CCO anything..." : "Start a new conversation..."}
              disabled={isStreaming}
              rows={1}
              className="flex-1 resize-none rounded-lg border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              style={{ minHeight: "2.5rem", maxHeight: "8rem" }}
              aria-label="Message input"
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = Math.min(target.scrollHeight, 128) + "px";
              }}
            />
            {isStreaming ? (
              <Button
                size="icon"
                variant="destructive"
                onClick={stopStreaming}
                className="shrink-0 h-10 w-10"
                aria-label="Stop generating"
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                size="icon"
                onClick={sendMessage}
                disabled={!input.trim()}
                className="shrink-0 h-10 w-10"
                aria-label="Send message"
              >
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
          <p className="text-[10px] text-muted-foreground text-center mt-2 max-w-3xl mx-auto">
            AI-generated responses may contain errors. Verify important information independently.
          </p>
        </div>
      </div>
    </div>
  );
}
