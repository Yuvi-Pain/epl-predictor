import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorState } from "./QueryState";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Catches render errors so one broken page does not blank the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          title="This page crashed"
          error={this.state.error}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
