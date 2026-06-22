import { useState } from "react";
import { Header } from "./components/Header";
import { ChatPanel } from "./components/ChatPanel";
import { QueryInput } from "./components/QueryInput";
import { ResultPanel } from "./components/ResultPanel";
import { LoadingState } from "./components/LoadingState";
import { ErrorBanner } from "./components/ErrorBanner";
import { SuggestedQuestions } from "./components/SuggestedQuestions";
import { ThreadControls } from "./components/ThreadControls";
import { useAgentQuery } from "./hooks/useAgentQuery";

export function App() {
  const { state, submit, newConversation } = useAgentQuery();
  const [inputText, setInputText] = useState("");

  const handleSubmit = (message: string) => {
    void submit(message);
  };

  const handleNewConversation = () => {
    setInputText("");
    newConversation();
  };

  return (
    <div className="flex flex-col h-screen">
      <Header>
        <ThreadControls
          threadId={state.threadId}
          onNewConversation={handleNewConversation}
        />
      </Header>
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-[18rem_minmax(22rem,0.9fr)_1.6fr] overflow-hidden">
        <aside
          aria-label="Suggested questions"
          className="border-b lg:border-b-0 lg:border-r border-slate-200 bg-white overflow-y-auto"
        >
          <SuggestedQuestions
            disabled={state.pending}
            onUse={(query) => setInputText(query)}
            onRun={(query) => handleSubmit(query)}
          />
        </aside>
        <section
          aria-label="Conversation"
          className="flex flex-col border-b lg:border-b-0 lg:border-r border-slate-200 bg-slate-50 min-h-0"
        >
          <div className="flex-1 overflow-hidden p-3 min-h-0">
            <ChatPanel messages={state.messages} />
          </div>
          <div className="border-t border-slate-200 bg-white p-3 flex flex-col gap-2">
            {state.error && <ErrorBanner error={state.error} />}
            {state.pending && <LoadingState />}
            <QueryInput
              disabled={state.pending}
              value={inputText}
              onChange={setInputText}
              onSubmit={handleSubmit}
            />
          </div>
        </section>
        <section aria-label="Result" className="overflow-y-auto p-4">
          <ResultPanel current={state.current} />
        </section>
      </main>
    </div>
  );
}
