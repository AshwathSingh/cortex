import { apiRequest } from "@/lib/api";

export const MAX_ASSISTANT_QUESTION_LENGTH = 4_000;
export const MAX_ASSISTANT_HISTORY_MESSAGES = 20;

export type AssistantCitationKind = "graph" | "sources";

export type AssistantCitation = {
  id: string;
  kind: AssistantCitationKind;
  label: string;
  description: string;
};

export type AssistantHistoryMessage = {
  role: "user" | "assistant";
  content: string;
};

export type AssistantResponse = {
  answer: string;
  citations: AssistantCitation[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseCitation(value: unknown): AssistantCitation {
  if (!isRecord(value)) throw new Error("Invalid assistant citation.");
  const { id, kind, label, description } = value;
  if (
    typeof id !== "string" ||
    !id ||
    (kind !== "graph" && kind !== "sources") ||
    typeof label !== "string" ||
    !label ||
    typeof description !== "string" ||
    !description
  ) {
    throw new Error("Invalid assistant citation.");
  }
  return { id, kind, label, description };
}

function parseAssistantResponse(value: unknown): AssistantResponse {
  if (!isRecord(value) || typeof value.answer !== "string" || !value.answer) {
    throw new Error("The assistant returned an invalid response.");
  }
  if (!Array.isArray(value.citations) || value.citations.length > 20) {
    throw new Error("The assistant returned invalid citations.");
  }
  return {
    answer: value.answer,
    citations: value.citations.map(parseCitation),
  };
}

export async function askAssistant({
  workspaceId,
  question,
  history,
  signal,
}: {
  workspaceId: string;
  question: string;
  history: AssistantHistoryMessage[];
  signal: AbortSignal;
}): Promise<AssistantResponse> {
  const response = await apiRequest<unknown>(
    `/api/workspaces/${workspaceId}/assistant/query`,
    {
      method: "POST",
      body: JSON.stringify({
        question,
        history: history.slice(-MAX_ASSISTANT_HISTORY_MESSAGES),
      }),
      signal,
    },
  );
  return parseAssistantResponse(response);
}
