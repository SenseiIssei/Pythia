import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="m-6 rounded-lg border border-danger/40 bg-danger/5 p-6">
          <div className="text-danger font-bold text-glow-red">Panel crashed</div>
          <pre className="mt-2 whitespace-pre-wrap text-xs text-cyber-text-dim">
            {this.state.error.message}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
