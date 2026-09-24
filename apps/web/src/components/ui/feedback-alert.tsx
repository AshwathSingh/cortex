type FeedbackAlertProps = {
  message: string | null;
};

export function FeedbackAlert({ message }: FeedbackAlertProps) {
  if (!message) {
    return null;
  }

  return (
    <p
      role="alert"
      className="mt-5 rounded-control border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
    >
      {message}
    </p>
  );
}
