import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

/* 全局错误边界：任何页面渲染崩溃都不再白屏（给出重载出口 + 保留报错信息可反馈） */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err) {
      return (
        <div style={{ padding: 40, fontFamily: "system-ui" }}>
          <h2 style={{ marginBottom: 12 }}>页面出错了（已拦截，不会白屏）</h2>
          <pre style={{ whiteSpace: "pre-wrap", background: "#f5f6f8", padding: 16, borderRadius: 8, fontSize: 12 }}>
            {String((this.state.err && (this.state.err.stack || this.state.err.message)) || this.state.err)}
          </pre>
          <button onClick={() => this.setState({ err: null })}>重试</button>{" "}
          <button onClick={() => { try { localStorage.removeItem("nl_assistant_sessions_v1"); } catch (e) {} location.reload(); }}>
            清理本地会话数据并刷新
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
