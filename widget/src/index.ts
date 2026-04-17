/**
 * Virchow Chat Widget - Entry Point
 * Exports the main web component
 */

import { VirchowChatWidget } from "./widget";

// Define the custom element
if (
  typeof customElements !== "undefined" &&
  !customElements.get("virchow-chat-widget")
) {
  customElements.define("virchow-chat-widget", VirchowChatWidget);
}

// Export for use in other modules
export { VirchowChatWidget };
export * from "./types/api-types";
export * from "./types/widget-types";
