"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

export type AssistantReference = {
  label: string;
  description: string;
  href: string;
};

export type AssistantTurn = {
  id: string;
  question: string;
  answer: string;
  references: AssistantReference[];
};

export type AssistantConversation = {
  id: string;
  title: string;
  turns: AssistantTurn[];
  updatedAt: number;
};

type WorkspaceConversationState = {
  conversations: AssistantConversation[];
  activeConversationId: string | null;
};

type ActiveConversationSelection = {
  workspaceId: string;
  conversationId: string | null;
};

type AssistantConversationContextValue = WorkspaceConversationState & {
  activeConversation: AssistantConversation | null;
  addTurn: (turn: Omit<AssistantTurn, "id">) => void;
  selectConversation: (conversationId: string) => void;
  startNewConversation: () => void;
};

const EMPTY_CONVERSATIONS: AssistantConversation[] = [];

const AssistantConversationContext =
  createContext<AssistantConversationContextValue | null>(null);

function createId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function conversationTitle(question: string) {
  const singleLine = question.replace(/\s+/g, " ").trim();
  return singleLine.length > 54 ? `${singleLine.slice(0, 51)}…` : singleLine;
}

export function AssistantConversationProvider({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: ReactNode;
}) {
  const [workspaceConversations, setWorkspaceConversations] = useState<
    Record<string, AssistantConversation[]>
  >({});
  const [activeSelection, setActiveSelection] =
    useState<ActiveConversationSelection>({
      workspaceId,
      conversationId: null,
    });

  const conversations =
    workspaceConversations[workspaceId] ?? EMPTY_CONVERSATIONS;
  const activeConversationId =
    activeSelection.workspaceId === workspaceId
      ? activeSelection.conversationId
      : null;

  const addTurn = useCallback(
    (turn: Omit<AssistantTurn, "id">) => {
      const now = Date.now();
      const nextTurn = { ...turn, id: createId() };
      const nextConversationId =
        activeConversationId &&
        conversations.some(
          (conversation) => conversation.id === activeConversationId,
        )
          ? activeConversationId
          : createId();

      setWorkspaceConversations((currentConversations) => {
        const workspaceItems =
          currentConversations[workspaceId] ?? EMPTY_CONVERSATIONS;
        const activeConversation = workspaceItems.find(
          (conversation) => conversation.id === activeConversationId,
        );

        if (!activeConversation) {
          const conversation: AssistantConversation = {
            id: nextConversationId,
            title: conversationTitle(turn.question),
            turns: [nextTurn],
            updatedAt: now,
          };
          return {
            ...currentConversations,
            [workspaceId]: [conversation, ...workspaceItems].slice(0, 20),
          };
        }

        const updatedConversation = {
          ...activeConversation,
          turns: [...activeConversation.turns, nextTurn],
          updatedAt: now,
        };
        return {
          ...currentConversations,
          [workspaceId]: [
            updatedConversation,
            ...workspaceItems.filter(
              (conversation) => conversation.id !== activeConversation.id,
            ),
          ],
        };
      });
      setActiveSelection({
        workspaceId,
        conversationId: nextConversationId,
      });
    },
    [activeConversationId, conversations, workspaceId],
  );

  const selectConversation = useCallback(
    (conversationId: string) => {
      if (
        !conversations.some(
          (conversation) => conversation.id === conversationId,
        )
      ) {
        return;
      }
      setActiveSelection({ workspaceId, conversationId });
    },
    [conversations, workspaceId],
  );

  const startNewConversation = useCallback(() => {
    setActiveSelection({ workspaceId, conversationId: null });
  }, [workspaceId]);

  const activeConversation =
    conversations.find(
      (conversation) => conversation.id === activeConversationId,
    ) ?? null;

  const value = useMemo(
    () => ({
      conversations,
      activeConversationId,
      activeConversation,
      addTurn,
      selectConversation,
      startNewConversation,
    }),
    [
      activeConversation,
      activeConversationId,
      addTurn,
      conversations,
      selectConversation,
      startNewConversation,
    ],
  );

  return (
    <AssistantConversationContext.Provider value={value}>
      {children}
    </AssistantConversationContext.Provider>
  );
}

export function useAssistantConversations() {
  const context = useContext(AssistantConversationContext);
  if (!context) {
    throw new Error(
      "useAssistantConversations must be used within AssistantConversationProvider.",
    );
  }
  return context;
}
