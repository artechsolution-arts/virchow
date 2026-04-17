import { css } from "lit";

/**
 * Virchow Chat Widget - Component Styles
 * All styling for the main widget component
 */
export const widgetStyles = css`
  :host {
    display: block;
    font-family: var(--virchow-font-family);
  }

  .launcher {
    position: fixed;
    background: var(--background-neutral-00);
    bottom: 20px;
    right: 20px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    color: var(--text-light-05);
    border: none;
    cursor: pointer;
    box-shadow: var(--shadow-02);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: var(--virchow-z-launcher);
    transition:
      transform 200ms cubic-bezier(0.4, 0, 0.2, 1),
      box-shadow 200ms cubic-bezier(0.4, 0, 0.2, 1),
      background 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  .launcher img {
    filter: drop-shadow(0px 1px 2px rgba(255, 255, 255, 0.3));
  }

  .launcher:hover {
    transform: translateY(-2px);
    background: var(--background-neutral-03);
    box-shadow: 0px 4px 20px rgba(0, 0, 0, 0.2);
  }

  .launcher:active {
    transform: translateY(0px);
    box-shadow: var(--shadow-02);
  }

  .container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    width: 400px;
    height: 600px;
    background: var(--background-neutral-00);
    border-radius: var(--virchow-radius-16);
    box-shadow: var(--shadow-02);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    z-index: var(--virchow-z-widget);
    border: 1px solid var(--border-01);
    animation: fadeInSlideUp 300ms cubic-bezier(0.4, 0, 0.2, 1) forwards;
    opacity: 0;
    transform: translateY(20px);
  }

  @keyframes fadeInSlideUp {
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .container.inline {
    position: static;
    width: 100%;
    height: 100%;
    border-radius: var(--virchow-radius-08);
    animation: none;
    opacity: 1;
    transform: none;
  }

  .container.inline.compact {
    background: transparent;
    border: none;
    box-shadow: none;
    border-radius: var(--virchow-radius-16);
  }

  @media (max-width: 768px) {
    .container:not(.inline) {
      position: fixed;
      inset: 0;
      width: 100vw;
      height: 100vh;
      border-radius: 0;
      bottom: 0;
      right: 0;
    }
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--virchow-space-md);
    background: var(--background-neutral-00);
    color: var(--text-04);
    border-bottom: 1px solid var(--border-01);
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: var(--virchow-space-sm);
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: var(--virchow-space-xs);
  }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: var(--background-neutral-00);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }

  .header-title {
    font-weight: 600;
    font-size: var(--virchow-font-size-label);
    line-height: var(--virchow-line-height-label);
    color: var(--text-04);
  }

  .icon-button {
    background: none;
    border: none;
    color: var(--text-04);
    cursor: pointer;
    padding: var(--virchow-space-xs);
    border-radius: var(--virchow-radius-08);
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background var(--virchow-transition-fast),
      color var(--virchow-transition-fast);
    font-size: 18px;
    width: 32px;
    height: 32px;
  }

  .icon-button:hover {
    background: var(--background-neutral-00);
    color: var(--text-04);
  }

  .messages {
    flex: 1;
    overflow-y: auto;
    padding: var(--virchow-space-md);
    display: flex;
    flex-direction: column;
    gap: var(--virchow-space-md);
    background: var(--background-neutral-00);
  }

  .message {
    display: flex;
    flex-direction: column;
    gap: var(--virchow-space-xs);
  }

  .message.user {
    align-items: flex-end;
  }

  .message.assistant {
    align-items: flex-start;
  }

  .message-bubble {
    max-width: 85%;
    padding: var(--virchow-space-sm) var(--virchow-space-md);
    border-radius: var(--virchow-radius-12);
    word-wrap: break-word;
    font-size: var(--virchow-font-size-main);
    line-height: var(--virchow-line-height-main);
  }

  .message.user .message-bubble {
    background: var(--virchow-user-message-bg);
    color: var(--text-04);
    border: 1px solid var(--border-01);
  }

  .message.assistant .message-bubble {
    background: var(--virchow-assistant-message-bg);
    color: var(--text-04);
    border: 1px solid var(--border-01);
  }

  /* Markdown styles */
  .message-bubble :first-child {
    margin-top: 0;
  }

  .message-bubble :last-child {
    margin-bottom: 0;
  }

  .message-bubble p {
    margin: 0.5em 0;
  }

  .message-bubble code {
    background: rgba(0, 0, 0, 0.08);
    padding: 2px 4px;
    border-radius: 3px;
    font-family: "Monaco", "Courier New", monospace;
    font-size: 0.9em;
  }

  .message-bubble pre {
    background: rgba(0, 0, 0, 0.08);
    padding: var(--virchow-space-sm);
    border-radius: var(--virchow-radius-sm);
    overflow-x: auto;
    margin: 0.5em 0;
  }

  .message-bubble pre code {
    background: none;
    padding: 0;
  }

  .message-bubble ul,
  .message-bubble ol {
    margin: 0.5em 0;
    padding-left: 1.5em;
  }

  .message-bubble li {
    margin: 0.25em 0;
  }

  .message-bubble a {
    color: var(--theme-primary-05);
    text-decoration: underline;
  }

  .message-bubble a:hover {
    text-decoration: none;
  }

  .message-bubble h1,
  .message-bubble h2,
  .message-bubble h3,
  .message-bubble h4,
  .message-bubble h5,
  .message-bubble h6 {
    margin: 0.5em 0 0.25em 0;
    font-weight: 600;
  }

  .message-bubble h1 {
    font-size: 1.5em;
  }
  .message-bubble h2 {
    font-size: 1.3em;
  }
  .message-bubble h3 {
    font-size: 1.1em;
  }

  .message-bubble blockquote {
    border-left: 3px solid var(--border-01);
    margin: 0.5em 0;
    padding-left: var(--virchow-space-md);
    color: var(--text-04);
  }

  .message-bubble strong {
    font-weight: 600;
  }

  .message-bubble em {
    font-style: italic;
  }

  .message-bubble hr {
    border: none;
    border-top: 1px solid var(--border-01);
    margin: 0.5em 0;
  }

  .status-container {
    display: flex;
    align-items: center;
    gap: var(--virchow-space-sm);
  }

  .typing-indicator {
    display: flex;
    gap: 4px;
  }

  .typing-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-04);
    animation: typing 1.4s infinite;
  }

  .typing-dot:nth-child(2) {
    animation-delay: 0.2s;
  }

  .typing-dot:nth-child(3) {
    animation-delay: 0.4s;
  }

  @keyframes typing {
    0%,
    60%,
    100% {
      opacity: 0.3;
      transform: translateY(0);
    }
    30% {
      opacity: 1;
      transform: translateY(-4px);
    }
  }

  .status-text {
    color: var(--text-04);
    font-size: var(--virchow-font-size-sm);
    font-style: italic;
  }

  .input-wrapper {
    border-top: 1px solid var(--border-01);
    background: var(--background-neutral-00);
  }

  .input-container {
    padding: var(--virchow-space-md) var(--virchow-space-md) 4px;
    display: flex;
    align-items: center;
    gap: var(--virchow-space-xs);
  }

  .input {
    flex: 1;
    min-width: 0;
    padding: var(--virchow-space-xs) var(--virchow-space-sm);
    border: 1px solid var(--theme-primary-05);
    border-radius: var(--virchow-radius-08);
    font-size: var(--virchow-font-size-main);
    line-height: var(--virchow-line-height-main);
    outline: none;
    font-family: var(--virchow-font-family);
    background: var(--background-neutral-00);
    color: var(--text-04);
    transition:
      border-color var(--virchow-transition-fast),
      box-shadow var(--virchow-transition-fast);
    height: 36px;
  }

  .input:focus {
    border-color: var(--theme-primary-05);
    outline: 2px solid var(--theme-primary-05);
    outline-offset: -2px;
  }

  .powered-by {
    font-size: 10px;
    color: var(--text-04);
    opacity: 0.5;
    text-align: center;
    padding: 0 var(--virchow-space-md) var(--virchow-space-xs);
  }

  .powered-by a {
    color: var(--text-04);
    text-decoration: none;
    transition: opacity var(--virchow-transition-fast);
  }

  .powered-by a:hover {
    opacity: 0.8;
    text-decoration: underline;
  }

  .send-button {
    background: var(--theme-primary-05);
    border: none;
    color: var(--text-light-05);
    cursor: pointer;
    padding: var(--virchow-space-sm);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background var(--virchow-transition-fast),
      transform var(--virchow-transition-fast);
    flex-shrink: 0;
    width: 36px;
    height: 36px;
  }

  .send-button svg {
    width: 18px;
    height: 18px;
  }

  .send-button:hover:not(:disabled) {
    background: var(--theme-primary-06);
    transform: scale(1.05);
  }

  .send-button:active:not(:disabled) {
    transform: scale(0.95);
  }

  .send-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .disclaimer {
    padding: var(--virchow-space-xs) var(--virchow-space-md);
    background: var(--background-neutral-00);
    color: var(--text-04);
    font-size: 11px;
    line-height: 1.3;
    text-align: center;
    border-bottom: 1px solid var(--border-01);
  }

  .error {
    padding: var(--virchow-space-md);
    background: var(--status-error-01);
    color: var(--status-error-05);
    border-radius: var(--virchow-radius-08);
    margin: var(--virchow-space-md);
    font-size: var(--virchow-font-size-main);
  }

  /* Compact inline mode (no messages) */
  .container.compact {
    height: auto;
    min-height: unset;
    border: none;
    box-shadow: none;
    background: transparent;
  }

  .compact-input-container {
    display: flex;
    align-items: center;
    gap: var(--virchow-space-sm);
    padding: var(--virchow-space-md);
    background: var(--background-neutral-00);
    border-radius: var(--virchow-radius-16);
    border: 1px solid var(--border-01);
    box-shadow: var(--shadow-02);
    transition:
      border-color var(--virchow-transition-base),
      box-shadow var(--virchow-transition-base);
  }

  .compact-input-container:focus-within {
    border-color: var(--text-04);
    box-shadow:
      var(--shadow-02),
      0 0 0 3px var(--background-neutral-00);
  }

  .compact-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--background-neutral-00);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--text-light-05);
    box-shadow: 0px 2px 8px rgba(0, 0, 0, 0.1);
  }

  .compact-input {
    flex: 1;
    min-width: 0;
    padding: var(--virchow-space-sm);
    border: none;
    font-size: var(--virchow-font-size-label);
    line-height: var(--virchow-line-height-label);
    outline: none;
    font-family: var(--virchow-font-family);
    background: transparent;
    color: var(--text-04);
    font-weight: 500;
  }

  .compact-input::placeholder {
    color: var(--text-04);
    font-weight: 400;
  }
`;
