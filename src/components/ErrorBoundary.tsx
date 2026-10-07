import { Component, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * One broken page must not take the app (and the stop button in the titlebar)
 * down with it. Says what happened in plain words, keeps the technical message
 * for a bug report, and offers a retry.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="mx-auto max-w-2xl rounded-xl border border-danger/40 bg-danger/5 p-5">
          <div className="flex items-start gap-3">
            <TriangleAlert size={20} aria-hidden className="mt-0.5 shrink-0 text-danger" />
            <div className="min-w-0">
              <div className="font-semibold text-danger">This page ran into a problem</div>
              <p className="mt-1 text-sm text-cyber-text-dim">
                The rest of the app keeps working, and the engine is not affected. The KILL button at the top still
                stops all new trades.
              </p>
              <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-cyber-border bg-cyber-bg/60 p-2 font-mono text-xs text-cyber-text-dim">
                {this.state.error.message}
              </pre>
              <button
                type="button"
                onClick={() => this.setState({ error: null })}
                className="mt-3 rounded-lg border border-cyber-border-bright bg-cyber-surface-2 px-3 py-1.5 text-sm text-cyber-text hover:bg-cyber-border-bright"
              >
                Try again
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
