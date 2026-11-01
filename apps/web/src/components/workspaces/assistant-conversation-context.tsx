"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import type {
  AssistantCitation,
  AssistantResponse,
} from "@/lib/assistant-client";

export type AssistantReference = AssistantCitation;

export type AssistantTurnStatus = "pending" | "complete" | "error";

export type AssistantTurn = {
  id: string;
  question: string;
  answer: string;
  references: AssistantReference[];
  status: AssistantTurnStatus;
  error: string | null;
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

export type AssistantTurnHandle = {
  conversationId: string;
  turnId: string;
};

type AssistantConversationContextValue = WorkspaceConversationState & {
  activeConversation: AssistantConversation | null;
  beginTurn: (question: string) => AssistantTurnHandle;
  completeTurn: (
    handle: AssistantTurnHandle,
    response: AssistantResponse,
  ) => void;
  failTurn: (handle: AssistantTurnHandle, message: string) => void;
  retryTurn: (handle: AssistantTurnHandle) => void;
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

  const beginTurn = useCallback(
    (question: string) => {
      const now = Date.now();
      const nextTurn: AssistantTurn = {
        id: createId(),
        question,
        answer: "",
        references: [],
        status: "pending",
        error: null,
      };
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
            title: conversationTitle(question),
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
      return {
        conversationId: nextConversationId,
        turnId: nextTurn.id,
      };
    },
    [activeConversationId, conversations, workspaceId],
  );

  const updateTurn = useCallback(
    (
      handle: AssistantTurnHandle,
      update: (turn: AssistantTurn) => AssistantTurn,
    ) => {
      setWorkspaceConversations((currentConversations) => {
        const workspaceItems =
          currentConversations[workspaceId] ?? EMPTY_CONVERSATIONS;
        const hasTarget = workspaceItems.some(
          (conversation) => conversation.id === handle.conversationId,
        );
        if (!hasTarget) return currentConversations;

        return {
          ...currentConversations,
          [workspaceId]: workspaceItems.map((conversation) =>
            conversation.id === handle.conversationId
              ? {
                  ...conversation,
                  updatedAt: Date.now(),
                  turns: conversation.turns.map((turn) =>
                    turn.id === handle.turnId ? update(turn) : turn,
                  ),
                }
              : conversation,
          ),
        };
      });
    },
    [workspaceId],
  );

  const completeTurn = useCallback(
    (handle: AssistantTurnHandle, response: AssistantResponse) => {
      updateTurn(handle, (turn) => ({
        ...turn,
        answer: response.answer,
        references: response.citations,
        status: "complete",
        error: null,
      }));
    },
    [updateTurn],
  );

  const failTurn = useCallback(
    (handle: AssistantTurnHandle, message: string) => {
      updateTurn(handle, (turn) => ({
        ...turn,
        status: "error",
        error: message,
      }));
    },
    [updateTurn],
  );

  const retryTurn = useCallback(
    (handle: AssistantTurnHandle) => {
      updateTurn(handle, (turn) => ({
        ...turn,
        answer: "",
        references: [],
        status: "pending",
        error: null,
      }));
    },
    [updateTurn],
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
      beginTurn,
      completeTurn,
      failTurn,
      retryTurn,
      selectConversation,
      startNewConversation,
    }),
    [
      activeConversation,
      activeConversationId,
      beginTurn,
      completeTurn,
      conversations,
      failTurn,
      retryTurn,
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
